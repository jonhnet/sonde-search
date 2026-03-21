#!/usr/bin/env python3
"""
SondeHound Pi BLE Service.

Listens for radiosonde_auto_rx UDP JSON telemetry and exposes it over
BLE as a GATT service. The Android app connects and subscribes to
telemetry notifications.

Requires BlueZ 5.43+ and the dbus-next library.

Usage:
    sudo python3 sondehound_ble.py [--udp-port 55673]
"""

import argparse
import asyncio
import json
import logging
import signal
from datetime import datetime, timedelta, timezone

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method, dbus_property, PropertyAccess
from dbus_next import Message, Variant, BusType

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sondehound")

# Must match the UUIDs in the Android app's BleService.kt
SERVICE_UUID = "1c98734f-0510-4fa8-b9c9-b9cea7a631b0"
TELEMETRY_CHAR_UUID = "f798a958-831b-46ba-bb3a-11a063c50ebc"
COMMAND_CHAR_UUID = "b12af15d-0713-4783-bd68-73b07d4b689b"

# BlueZ D-Bus constants
BLUEZ_SERVICE = "org.bluez"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
ADAPTER_IFACE = "org.bluez.Adapter1"


class BleGattServer:
    """Manages the BLE GATT server using BlueZ D-Bus API."""

    def __init__(self):
        self.bus = None
        self.adapter_path = None
        self.latest_telemetry = b""
        self.notify_callback = None
        self._command_callback = None

    async def setup(self):
        """Initialize D-Bus connection and find the Bluetooth adapter."""
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        # Find the first Bluetooth adapter
        introspect = await self.bus.introspect(BLUEZ_SERVICE, "/org/bluez")
        for node in introspect.nodes:
            self.adapter_path = f"/org/bluez/{node.name}"
            break

        if not self.adapter_path:
            raise RuntimeError("No Bluetooth adapter found")

        log.info(f"Using adapter: {self.adapter_path}")

        # Power on the adapter and make it discoverable
        adapter = self.bus.get_proxy_object(
            BLUEZ_SERVICE, self.adapter_path,
            await self.bus.introspect(BLUEZ_SERVICE, self.adapter_path)
        )
        adapter_props = adapter.get_interface("org.freedesktop.DBus.Properties")
        await adapter_props.call_set(ADAPTER_IFACE, "Powered", Variant("b", True))
        await adapter_props.call_set(ADAPTER_IFACE, "Alias", Variant("s", "SondeHound"))

        log.info("Bluetooth adapter powered on")

    async def register_application(self):
        """Register our GATT application with BlueZ."""
        app = SondeHoundGattApp(self)

        # Export on D-Bus
        self.bus.export("/com/sondehound", app)
        self.bus.export("/com/sondehound/service0", app.service)
        self.bus.export("/com/sondehound/service0/char0", app.telemetry_char)
        self.bus.export("/com/sondehound/service0/char1", app.command_char)

        # Register with BlueZ GATT manager
        gatt_mgr = self.bus.get_proxy_object(
            BLUEZ_SERVICE, self.adapter_path,
            await self.bus.introspect(BLUEZ_SERVICE, self.adapter_path)
        )
        manager = gatt_mgr.get_interface(GATT_MANAGER_IFACE)
        await manager.call_register_application("/com/sondehound", {})

        log.info("GATT application registered")

    async def start_advertising(self):
        """Start BLE advertising so the Android app can discover us."""
        adv = SondeHoundAdvertisement()
        self.bus.export("/com/sondehound/adv0", adv)

        adv_mgr = self.bus.get_proxy_object(
            BLUEZ_SERVICE, self.adapter_path,
            await self.bus.introspect(BLUEZ_SERVICE, self.adapter_path)
        )
        manager = adv_mgr.get_interface(LE_ADVERTISING_MANAGER_IFACE)
        await manager.call_register_advertisement("/com/sondehound/adv0", {})

        log.info("BLE advertising started")

    def send_telemetry(self, json_bytes: bytes):
        """Send a telemetry update to subscribed BLE clients.

        Fragments the message into chunks that fit the BLE MTU and
        terminates with a newline so the client knows the message is complete.
        """
        self.latest_telemetry = json_bytes
        if self.notify_callback:
            # Fragment into ~180 byte chunks (conservative for default MTU)
            data = json_bytes + b"\n"
            chunk_size = 180
            log.debug(f"Sending {len(data)} bytes in {(len(data) + chunk_size - 1) // chunk_size} chunk(s) via BLE notify")
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                try:
                    self.notify_callback(chunk)
                except Exception as e:
                    log.error(f"Notify failed: {e}")
                    break
        else:
            log.debug("No notify callback registered, skipping BLE send")

    def set_command_callback(self, callback):
        """Set callback for when a command is received from the Android app."""
        self._command_callback = callback

    def handle_command(self, data: bytes):
        """Process a command received from the Android app."""
        try:
            cmd = json.loads(data.decode("utf-8"))
            log.info(f"Received command: {cmd}")
            if self._command_callback:
                self._command_callback(cmd)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning(f"Invalid command: {e}")


class SondeHoundGattApp(ServiceInterface):
    """D-Bus GATT Application containing our service."""

    def __init__(self, server: BleGattServer):
        super().__init__("org.freedesktop.DBus.ObjectManager")
        self.service = SondeHoundService()
        self.telemetry_char = TelemetryCharacteristic(server)
        self.command_char = CommandCharacteristic(server)

    @method()
    def GetManagedObjects(self) -> "a{oa{sa{sv}}}":
        return {
            "/com/sondehound/service0": {
                "org.bluez.GattService1": {
                    "UUID": Variant("s", SERVICE_UUID),
                    "Primary": Variant("b", True),
                    "Characteristics": Variant(
                        "ao",
                        [
                            "/com/sondehound/service0/char0",
                            "/com/sondehound/service0/char1",
                        ],
                    ),
                }
            },
            "/com/sondehound/service0/char0": {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", TELEMETRY_CHAR_UUID),
                    "Service": Variant("o", "/com/sondehound/service0"),
                    "Flags": Variant("as", ["read", "notify"]),
                }
            },
            "/com/sondehound/service0/char1": {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", COMMAND_CHAR_UUID),
                    "Service": Variant("o", "/com/sondehound/service0"),
                    "Flags": Variant("as", ["write", "write-without-response"]),
                }
            },
        }


class SondeHoundService(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.GattService1")

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> "s":
        return SERVICE_UUID

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> "b":
        return True


class TelemetryCharacteristic(ServiceInterface):
    CHAR_PATH = "/com/sondehound/service0/char0"

    def __init__(self, server: BleGattServer):
        super().__init__("org.bluez.GattCharacteristic1")
        self.server = server
        self.notifying = False

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> "s":
        return TELEMETRY_CHAR_UUID

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> "o":
        return "/com/sondehound/service0"

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> "as":
        return ["read", "notify"]

    @method()
    def ReadValue(self, options: "a{sv}") -> "ay":
        return bytes(self.server.latest_telemetry)

    @method()
    def StartNotify(self) -> None:
        self.notifying = True
        log.info("Client subscribed to telemetry notifications")

        def notify(data: bytes):
            if not self.notifying or not self.server.bus:
                return
            # Emit PropertiesChanged signal directly on the D-Bus
            # This is what BlueZ listens for to send BLE notifications
            msg = Message.new_signal(
                path=self.CHAR_PATH,
                interface="org.freedesktop.DBus.Properties",
                member="PropertiesChanged",
                signature="sa{sv}as",
                body=[
                    "org.bluez.GattCharacteristic1",
                    {"Value": Variant("ay", bytes(data))},
                    [],
                ],
            )
            self.server.bus.send(msg)

        self.server.notify_callback = notify

        # Replay the most recent telemetry so the client gets data immediately
        if self.server.latest_telemetry:
            log.info("Replaying last telemetry to new subscriber")
            self.server.send_telemetry(self.server.latest_telemetry)

    @method()
    def StopNotify(self) -> None:
        self.notifying = False
        self.server.notify_callback = None
        log.info("Client unsubscribed from telemetry notifications")


class CommandCharacteristic(ServiceInterface):
    def __init__(self, server: BleGattServer):
        super().__init__("org.bluez.GattCharacteristic1")
        self.server = server

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> "s":
        return COMMAND_CHAR_UUID

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> "o":
        return "/com/sondehound/service0"

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> "as":
        return ["write", "write-without-response"]

    @method()
    def WriteValue(self, value: "ay", options: "a{sv}") -> None:
        self.server.handle_command(bytes(value))


class SondeHoundAdvertisement(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.LEAdvertisement1")

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":
        return "peripheral"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> "as":
        return [SERVICE_UUID]

    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> "s":
        return "SondeHound"

    @dbus_property(access=PropertyAccess.READ)
    def Includes(self) -> "as":
        return ["tx-power"]

    @method()
    def Release(self) -> None:
        log.info("Advertisement released")


class UdpListener:
    """Listens for auto_rx UDP JSON packets and forwards them to BLE."""

    def __init__(self, ble_server: BleGattServer, port: int):
        self.ble_server = ble_server
        self.port = port

    async def run(self):
        """Listen for UDP packets and forward to BLE."""
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: AutoRxProtocol(self.ble_server),
            local_addr=("0.0.0.0", self.port),
        )
        log.info(f"Listening for auto_rx UDP on port {self.port}")
        return transport


class AutoRxProtocol(asyncio.DatagramProtocol):
    def __init__(self, ble_server: BleGattServer):
        self.ble_server = ble_server

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data)

            # Convert HH:MM:SS time field to epoch timestamp
            time_str = msg.get("time", "")
            if time_str:
                try:
                    now_utc = datetime.now(timezone.utc)
                    t = datetime.strptime(time_str, "%H:%M:%S").replace(
                        year=now_utc.year, month=now_utc.month, day=now_utc.day,
                        tzinfo=timezone.utc
                    )
                    # Handle midnight rollover: if parsed time is more than
                    # 12 hours ahead of now, assume it was yesterday
                    if (t - now_utc).total_seconds() > 43200:
                        t -= timedelta(days=1)
                    msg["time_epoch"] = int(t.timestamp())
                except ValueError:
                    pass

            log.info(
                f"Rx from {addr}: {msg.get('callsign', '?')} "
                f"({msg.get('model', '?')}) "
                f"alt={msg.get('altitude', '?')}m "
                f"({msg.get('latitude', '?')}, {msg.get('longitude', '?')})"
            )
            self.ble_server.send_telemetry(json.dumps(msg).encode("utf-8"))
        except json.JSONDecodeError:
            log.warning(f"Invalid JSON from {addr}")


async def main():
    parser = argparse.ArgumentParser(description="SondeHound Pi BLE Service")
    parser.add_argument(
        "--udp-port", type=int, default=55673, help="auto_rx UDP port (default: 55673)"
    )
    args = parser.parse_args()

    ble = BleGattServer()
    await ble.setup()
    await ble.register_application()
    await ble.start_advertising()

    # Handle mode commands from the Android app
    def on_command(cmd):
        mode = cmd.get("mode")
        if mode == "auto":
            log.info("Switching to AUTO mode")
            # TODO: send command to auto_rx to switch to scan mode
        elif mode == "frequency":
            freq = cmd.get("freq", 403.0)
            log.info(f"Switching to FREQUENCY mode: {freq} MHz")
            # TODO: send command to auto_rx to lock on frequency

    ble.set_command_callback(on_command)

    udp = UdpListener(ble, args.udp_port)
    await udp.run()

    log.info("SondeHound BLE service running. Press Ctrl+C to stop.")

    # Run until cancelled
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    await stop_event.wait()

    log.info("Shutting down.")


if __name__ == "__main__":
    asyncio.run(main())
