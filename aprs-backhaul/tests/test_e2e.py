"""End-to-end: auto_rx UDP -> pi daemon -> KISS TCP -> cloud handler -> uploader.

Runs entirely in-process:
- A fake Direwolf KISS server accepts a TCP connection and buffers bytes.
- The real AprsPiGateway is driven via synthesized PAYLOAD_SUMMARY messages.
- KISS bytes are decoded into AX.25 frames, reformatted as TNC2 strings,
  re-parsed through aprslib exactly as they would be on the cloud side,
  and fed to the real PacketHandler with a mock uploader.
"""

import asyncio
import json
import socket
from datetime import datetime, timezone
from unittest.mock import MagicMock

import aprslib
import pytest

from cloud.aprs_cloud_gateway import (
    CloudConfig,
    FrameDedup,
    PacketHandler,
    ReceptionLogger,
)
from lib import aprs_encoding as ae
from lib.auto_rx_udp import listen as udp_listen
from pi.aprs_pi_gateway import AprsPiGateway, Config, KissTncClient

# Short rate-limit so the coalescer's self-scheduling tasks fire within
# test timeouts rather than on production's 60s cadence.
WINDOW = 0.05
WAIT = WINDOW * 2.0


class FakeKissServer:
    def __init__(self):
        self.received = bytearray()
        self._server: asyncio.base_events.Server | None = None
        self.port = 0
        self._clients: list[asyncio.StreamWriter] = []
        self._ready = asyncio.Event()

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._clients.append(writer)
        self._ready.set()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                self.received.extend(chunk)
        finally:
            writer.close()

    async def wait_client(self) -> None:
        await self._ready.wait()

    async def stop(self) -> None:
        for w in self._clients:
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


def _make_payload_summary(serial: str, frame: int, alt: float = 25310.0) -> dict:
    return {
        "callsign": serial,
        "latitude": 47.608,
        "longitude": -122.335,
        "altitude": alt,
        "frame": frame,
        "snr": 12.3,
        "freq": "403.500 MHz",
        "model": "RS41",
    }


def _frame_to_tnc2(frame: bytes) -> str:
    source, dest, path, info = ae.parse_ui_frame(frame)
    parts = [source, ">", dest]
    if path:
        parts.append(",")
        parts.append(",".join(path))
    parts.append(":")
    parts.append(info)
    return "".join(parts)


async def test_e2e_pi_to_cloud_latest_wins():
    """First obs TXes immediately; later ones buffered; after the window
    the latest pending hits the wire and flows through the cloud handler."""
    kiss_server = FakeKissServer()
    await kiss_server.start()

    pi_cfg = Config(
        callsign="KK7YBO",
        kiss_host="127.0.0.1", kiss_port=kiss_server.port,
        tocall="APZSDH", path=[], min_interval_sec=WINDOW,
        # Keep tasks running for the duration of the test by requiring
        # more idle windows than we actually wait out.
        idle_windows_before_eof=100,
    )
    kiss_client = KissTncClient(pi_cfg.kiss_host, pi_cfg.kiss_port)
    gateway = AprsPiGateway(pi_cfg, kiss_client, now_fn=lambda: 1_700_000_000.0)
    try:
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=10)
        )
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=11)
        )
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=12)
        )
        # A second sonde shows up; fires immediately.
        await gateway.on_payload_summary(
            _make_payload_summary("M0123456", frame=500)
        )
        # Wait for the timer to tick past the window boundary.
        await asyncio.sleep(WAIT)
    finally:
        await gateway.coalescer.stop()

    await kiss_server.wait_client()
    await kiss_client.close()

    frames = ae.kiss_unframe(bytes(kiss_server.received))
    cloud_cfg = CloudConfig(
        aprsis_callsign="N0CALL",
        reception_log_path="/dev/null",
        tocall="APZSDH",
    )
    reception_logger = ReceptionLogger(cloud_cfg.reception_log_path)
    uploader = MagicMock()
    dedup = FrameDedup(ttl_sec=3600)
    handler = PacketHandler(
        cloud_cfg, reception_logger, uploader, dedup,
        now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31, tzinfo=timezone.utc),
    )
    for fr in frames:
        handler(aprslib.parse(_frame_to_tnc2(fr)))
    reception_logger.close()

    records = [call.args[0] for call in uploader.add.call_args_list]
    pairs = sorted((r["serial"], r["frame"]) for r in records)
    assert pairs == [("M0123456", 500), ("S4310587", 10), ("S4310587", 12)]
    for r in records:
        assert abs(r["lat"] - 47.608) < 0.001
        assert abs(r["lon"] - (-122.335)) < 0.001
        assert r["type"] == "RS41"
        # uploader_callsign was derived from the APRS source "KK7YBO-12".
        assert r["uploader_callsign"] == "KK7YBO_APRS"

    await kiss_server.stop()


async def test_e2e_end_of_flight_redundant_finals_plus_killed():
    """Sonde goes silent; the gateway emits N live final-position reports
    plus one killed-object packet, then the per-serial task exits."""
    kiss_server = FakeKissServer()
    await kiss_server.start()

    pi_cfg = Config(
        callsign="KK7YBO",
        kiss_host="127.0.0.1", kiss_port=kiss_server.port,
        tocall="APZSDH", path=[], min_interval_sec=WINDOW,
        idle_windows_before_eof=1,
        final_redundancy=2,
        final_spacing_sec=0.0,
    )
    kiss_client = KissTncClient(pi_cfg.kiss_host, pi_cfg.kiss_port)
    gateway = AprsPiGateway(pi_cfg, kiss_client, now_fn=lambda: 1_700_000_000.0)
    try:
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=1)
        )
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=99, alt=500.0)
        )
        await gateway.on_payload_summary(
            _make_payload_summary("S4310587", frame=100, alt=50.0)
        )
        # Wait enough windows for: flush + idle + EOF actions.
        await asyncio.sleep(WINDOW * 4)
        assert "S4310587" not in gateway.coalescer._tasks
    finally:
        await gateway.coalescer.stop()

    await kiss_server.wait_client()
    await kiss_client.close()

    frames = ae.kiss_unframe(bytes(kiss_server.received))
    # Expected: initial (frame 1 live) + flush (frame 100 live) +
    #           2 redundant final (frame 100 live) + 1 killed (frame 100 dead)
    assert len(frames) == 5

    pkts = [
        aprslib.parse(_frame_to_tnc2(fr))
        for fr in frames
    ]
    cmts = [ae.parse_sonde_comment(p["comment"]) for p in pkts]

    assert [p["alive"] for p in pkts] == [True, True, True, True, False]
    assert [c.frame for c in cmts] == [1, 100, 100, 100, 100]
    # killed-object carries the last-known altitude in /A= (parsed by aprslib).
    assert pkts[-1]["altitude"] == pytest.approx(50, abs=1)

    await kiss_server.stop()


async def test_e2e_cloud_dedups_aprs_duplicates():
    """An iGate duplicate (same serial+frame) must not upload twice."""
    cloud_cfg = CloudConfig(
        aprsis_callsign="N0CALL",
        reception_log_path="/dev/null",
        tocall="APZSDH",
    )
    reception_logger = ReceptionLogger(cloud_cfg.reception_log_path)
    uploader = MagicMock()
    dedup = FrameDedup(ttl_sec=3600)
    handler = PacketHandler(
        cloud_cfg, reception_logger, uploader, dedup,
        now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31, tzinfo=timezone.utc),
    )
    tnc2 = (
        "KK7YBO-10>APZSDH:;S4310587 *181530z"
        "4003.00N/10515.00WOF2345 S12.3 f403.000 tA/A=083038!W00!"
    )
    pkt = aprslib.parse(tnc2)
    handler(pkt)
    handler(pkt)
    handler(pkt)
    assert uploader.add.call_count == 1


async def test_e2e_udp_to_kiss_via_real_sockets():
    """Sanity-check the full UDP → KISS transport chain using the real UDP
    listener end-to-end."""
    kiss_server = FakeKissServer()
    await kiss_server.start()

    pi_cfg = Config(
        callsign="KK7YBO",
        kiss_host="127.0.0.1", kiss_port=kiss_server.port,
        tocall="APZSDH", path=[], min_interval_sec=WINDOW,
        idle_windows_before_eof=100,
    )
    kiss_client = KissTncClient(pi_cfg.kiss_host, pi_cfg.kiss_port)
    gateway = AprsPiGateway(pi_cfg, kiss_client, now_fn=lambda: 1_700_000_000.0)

    async def on_msg(msg):
        await gateway.on_payload_summary(msg)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    udp_port = sock.getsockname()[1]
    sock.close()

    transport = await udp_listen(udp_port, on_msg, host="127.0.0.1")

    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.sendto(
        json.dumps(_make_payload_summary("S4310587", 1)).encode("utf-8"),
        ("127.0.0.1", udp_port),
    )
    send_sock.close()

    await kiss_server.wait_client()
    await asyncio.sleep(0.1)

    frames = ae.kiss_unframe(bytes(kiss_server.received))
    assert len(frames) == 1
    source, dest, _, _info = ae.parse_ui_frame(frames[0])
    assert source == "KK7YBO-12"
    assert dest == "APZSDH"
    pkt = aprslib.parse(_frame_to_tnc2(frames[0]))
    assert pkt["object_name"].strip() == "S4310587"

    transport.close()
    await gateway.coalescer.stop()
    await kiss_client.close()
    await kiss_server.stop()
