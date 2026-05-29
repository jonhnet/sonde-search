#!/usr/bin/env python3
"""
Shared library for GPP4323 Power Supply interface and data handling
"""

import socket
import time
from typing import Callable, Tuple, Optional
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class LoadReading:
    """Data structure for a single load reading"""
    voltage: float
    current: float
    power: float
    timestamp: datetime


class GPP4323:
    """Driver for GW Instek GPP4323 Power Supply"""

    def __init__(self, host: str, port: int = 1026, timeout: float = 1.0,
                 cmd_delay: float = 0.1, mode_switch_timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        # The GPP4323 silently drops commands sent back-to-back with no gap,
        # so pace fire-and-forget commands by this many seconds.
        self.cmd_delay = cmd_delay
        # A source/load mode change throws a mechanical relay; the channel is
        # unresponsive for a variable ~1-2 s while it settles. Rather than guess
        # a fixed delay, mode changes poll until the channel reports the new
        # mode, giving up after this many seconds.
        self.mode_switch_timeout = mode_switch_timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> None:
        """Establish connection to the power supply"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        print(f"Connected to GPP4323 at {self.host}:{self.port}")

    def disconnect(self) -> None:
        """Close connection to the power supply"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_command(self, command: str) -> None:
        """Send a command to the power supply.

        Sleeps for cmd_delay afterwards: the GPP4323 drops commands that
        arrive without a gap between them. Queries are self-pacing (they block
        on the reply) so they don't need this.
        """
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{command}\n".encode())
        if self.cmd_delay:
            time.sleep(self.cmd_delay)

    def _drain(self) -> None:
        """Discard any stale buffered reply before sending the next query.

        The GPP4323 can leave a reply in the socket after a read times out;
        if it is not cleared it lands in the next query's recv, desyncing every
        subsequent reply (a voltage reading turning up in a current read, etc.).
        Draining before each query keeps replies matched to their commands.
        """
        self.sock.setblocking(False)
        try:
            while self.sock.recv(4096):
                pass
        except BlockingIOError:
            pass
        finally:
            self.sock.settimeout(self.timeout)

    def query(self, command: str) -> str:
        """Send a query and return the response"""
        if not self.sock:
            raise RuntimeError("Not connected")
        self._drain()
        self.sock.sendall(f"{command}\n".encode())
        response = self.sock.recv(1024).decode().strip()
        return response

    @staticmethod
    def _parse_reading(response: str, unit: str) -> float:
        """Convert a GPP4323 numeric reply (e.g. '13.604V') to a float.

        Requires the expected unit suffix ('V' for VOUT?, 'A' for IOUT?). A
        reply carrying the wrong unit means it is desynced from its query, so
        raise rather than silently return the wrong quantity (a voltage handed
        back as a current would be data corruption).
        """
        text = response.strip()
        if not text.endswith(unit):
            raise ValueError(
                f"expected a reading in {unit!r}, got {response!r} "
                f"(reply desynced from query)")
        return float(text[:-len(unit)])

    def get_idn(self) -> str:
        """Get instrument identification"""
        return self.query("*IDN?")

    def set_voltage(self, channel: int, volts: float) -> None:
        """Set the source voltage of a channel (power mode)"""
        self.send_command(f":SOURce{channel}:VOLTage {volts:.4f}")

    def set_current(self, channel: int, amps: float) -> None:
        """Set a channel's current level.

        In power mode this is the current limit; in CC-load mode it is the
        sink (load) current. The GPP4323 uses the same SOURce:CURRent command
        for both.
        """
        self.send_command(f":SOURce{channel}:CURRent {amps:.4f}")

    def set_output(self, channel: int, on: bool) -> None:
        """Enable or disable a channel's output"""
        self.send_command(f":OUTPut{channel}:STATe {'ON' if on else 'OFF'}")

    def set_load_cc(self, channel: int, on: bool) -> None:
        """Enable/disable constant-current electronic-load mode (CH1/CH2 only).

        Turning it off returns the channel to normal power (source) mode.
        Blocks until the channel reports the new mode.
        """
        if channel not in (1, 2):
            raise ValueError("Load mode is only available on channels 1 and 2")
        self.send_command(f":LOAD{channel}:CC {'ON' if on else 'OFF'}")
        self._await_mode(channel, 'CC' if on else 'IND')

    def set_load_cv(self, channel: int, on: bool) -> None:
        """Enable/disable constant-voltage electronic-load mode (CH1/CH2 only).

        Blocks until the channel reports the new mode.
        """
        if channel not in (1, 2):
            raise ValueError("Load mode is only available on channels 1 and 2")
        self.send_command(f":LOAD{channel}:CV {'ON' if on else 'OFF'}")
        self._await_mode(channel, 'CV' if on else 'IND')

    def set_source_mode(self, channel: int) -> None:
        """Put a channel into normal power (source) mode, clearing load mode.

        Blocks until the channel reports independent (source) mode.
        """
        if channel in (1, 2):
            self.send_command(f":LOAD{channel}:CC OFF")
            self.send_command(f":LOAD{channel}:CV OFF")
            self._await_mode(channel, 'IND')

    def get_mode(self, channel: int) -> str:
        """Query a channel's operating mode.

        Returns a short token: 'IND' (independent source), 'CC'/'CV'/'CR'
        (load modes), or 'SER'/'PAR' (tracking).
        """
        return self.query(f":MODE{channel}?")

    def _await_mode(self, channel: int, expected: str) -> None:
        """Block until a channel reports `expected` mode after a mode change.

        While the mode-switch relay settles the channel withholds its reply to
        the first :MODE? for over a second, so this temporarily extends the
        recv timeout to wait that reply out rather than polling fast and racing
        it. Raises if the mode is never reached within mode_switch_timeout.
        """
        deadline = time.monotonic() + self.mode_switch_timeout
        saved_timeout = self.timeout
        self.timeout = self.mode_switch_timeout
        if self.sock:
            self.sock.settimeout(self.timeout)
        last = None
        try:
            while time.monotonic() < deadline:
                try:
                    last = self.get_mode(channel)
                    if last.startswith(expected):
                        return
                except TimeoutError:
                    last = "(no response)"
            raise RuntimeError(
                f"CH{channel} did not reach {expected!r} mode within "
                f"{self.mode_switch_timeout}s (last reply: {last!r})")
        finally:
            self.timeout = saved_timeout
            if self.sock:
                self.sock.settimeout(self.timeout)

    def get_channel_load(self, channel: int = 1) -> Tuple[float, float, float]:
        """Get load reading from specified channel

        Returns:
            tuple: (voltage, current, power) in V, A, W
        """
        voltage = self._parse_reading(self.query(f"VOUT{channel}?"), 'V')
        current = self._parse_reading(self.query(f"IOUT{channel}?"), 'A')
        power = voltage * current
        return voltage, current, power


class DataCollector:
    """Collects data from a GPP4323 channel at specified sampling rate"""

    def __init__(self,
                 psu: GPP4323,
                 channel: int = 1,
                 rate: float = 10.0,
                 callback: Optional[Callable[[LoadReading], None]] = None,
                 load_voltage: Optional[float] = None):
        """
        Initialize data collector

        Args:
            psu: GPP4323 instance to collect data from
            channel: Channel number to monitor (default: 1)
            rate: Sampling rate in Hz
            callback: Function called with each new LoadReading
            load_voltage: If set, configure the channel as a constant-voltage
                electronic load at this voltage (V) and enable its output
                before collecting.
        """
        self.psu = psu
        self.channel = channel
        self.rate = rate
        self.interval = 1.0 / rate
        self.callback = callback
        self.load_voltage = load_voltage
        self.is_running = False

    def start(self) -> None:
        """Start data collection loop"""
        self.is_running = True

        # Get instrument ID
        idn = self.psu.get_idn()
        print(f"Instrument: {idn}")

        # Configure the channel as a constant-voltage load if requested.
        if self.load_voltage is not None:
            self.psu.set_load_cv(self.channel, True)
            self.psu.set_voltage(self.channel, self.load_voltage)
            self.psu.set_output(self.channel, True)
            print(f"CH{self.channel} set as CV load at {self.load_voltage} V")

        # Set to local mode so front panel remains usable
        self.psu.send_command("LOCAL")
        print("Set to LOCAL mode")

        print(f"Data collection started at {self.rate} Hz on channel {self.channel}")

        next_sample = time.monotonic()
        while self.is_running:
            try:
                voltage, current, power = self.psu.get_channel_load(channel=self.channel)
                timestamp = datetime.now(timezone.utc)
                reading = LoadReading(voltage, current, power, timestamp)
                if self.callback:
                    self.callback(reading)
            except socket.timeout:
                print("Warning: power supply read timed out, retrying")

            next_sample += self.interval
            sleep_time = next_sample - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # Fell behind — reset to avoid burst of catch-up samples
                next_sample = time.monotonic()

    def stop(self) -> None:
        """Stop data collection"""
        self.is_running = False
        print("Data collection stopped")
