#!/usr/bin/env python3
"""APRS Pi-side gateway: auto_rx UDP → Direwolf KISS TCP.

Subscribes to radiosonde_auto_rx's PAYLOAD_SUMMARY broadcast on UDP 55673,
rate-limits per sonde, and emits APRS object beacons via Direwolf's KISS
TCP interface.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

# Allow running this file directly from pi/ — add the aprs-backhaul/ root
# (parent of pi/) to sys.path so `from lib import ...` works without the
# caller having to set PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from lib import aprs_encoding as ae  # noqa: E402
from lib.auto_rx_udp import listen as udp_listen  # noqa: E402

log = logging.getLogger("aprs-backhaul-pi")

# Hard-coded APRS SSID for the RF gateway.
# The APRS SSID convention reserves -12 for "one-way trackers" — stations
# that transmit position data without being a two-way operator. That fits
# our use exactly: we beacon sonde positions but don't receive / ack / QSO.
# Hard-coding this (rather than making it configurable) keeps all sonde
# gateways consistent on the air, so downstream tools can filter on SSID.
# See https://www.aprs.org/aprs11/SSIDs.txt.
GATEWAY_SSID = 12


@dataclass
class Config:
    callsign: str
    udp_port: int = 55673
    kiss_host: str = "127.0.0.1"
    kiss_port: int = 8001
    tocall: str = "APZSDH"
    min_interval_sec: float = 120.0
    # End-of-flight: after this many consecutive silent windows, consider
    # the sonde lost and emit redundant final position reports plus a
    # killed-object marker. With the 120 s window default, 3 windows =
    # 6 minutes of silence before EOF fires.
    idle_windows_before_eof: int = 3
    final_redundancy: int = 2
    final_spacing_sec: float = 10.0
    path: list[str] = field(default_factory=lambda: ["WIDE1-1", "WIDE2-1"])
    log_level: str = "INFO"


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    callsign = raw.get("callsign")
    if not callsign:
        raise ValueError(
            f"{path}: `callsign` is required "
            "(amateur-radio callsign of the RF gateway)"
        )
    return Config(
        callsign=str(callsign).upper(),
        udp_port=int(raw.get("udp_port", 55673)),
        kiss_host=str(raw.get("kiss_host", "127.0.0.1")),
        kiss_port=int(raw.get("kiss_port", 8001)),
        tocall=str(raw.get("tocall", "APZSDH")).upper(),
        min_interval_sec=float(raw.get("min_interval_sec", 120.0)),
        idle_windows_before_eof=int(raw.get("idle_windows_before_eof", 3)),
        final_redundancy=int(raw.get("final_redundancy", 2)),
        final_spacing_sec=float(raw.get("final_spacing_sec", 10.0)),
        path=[str(p) for p in raw.get("path", ["WIDE1-1", "WIDE2-1"])],
        log_level=str(raw.get("log_level", "INFO")).upper(),
    )


TransmitFn = Callable[..., Awaitable[None]]  # (data, live: bool) -> None


class LatestCoalescer:
    """Per-serial rate control with self-scheduling tasks.

    On the first observation for a serial, transmit immediately and spawn
    a per-serial flush task. The task sleeps `min_interval_sec`, then:
      - if a later observation was buffered while it slept, TX the latest
        and loop;
      - else increment the idle counter; after `idle_window_threshold`
        consecutive idle windows, enter end-of-flight (EOF).

    EOF transmits the last known position `final_redundancy` times with
    `final_spacing_sec` gaps, then one final killed-object packet. At the
    start of each gap the coalescer checks `_pending`; if a new observation
    landed during EOF, the sequence is abandoned and the task resumes the
    normal loop. That way a sonde that briefly re-appears doesn't get a
    killed-object beacon broadcast for it.
    """

    def __init__(self, min_interval_sec: float,
                 transmit: TransmitFn,
                 idle_window_threshold: int = 3,
                 final_redundancy: int = 2,
                 final_spacing_sec: float = 10.0):
        # `transmit` is invoked as `await transmit(data, live=True)` for
        # every normal/redundant-final beacon and `await transmit(data,
        # live=False)` for the single killed-object packet at EOF.
        self._min = min_interval_sec
        self._transmit = transmit
        self._idle_threshold = idle_window_threshold
        self._final_redundancy = final_redundancy
        self._final_spacing = final_spacing_sec
        self._pending: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._last_data: dict[str, Any] = {}

    async def new_observation(self, data: dict) -> None:
        """Record an observation. `data` must be a dict with a `serial` key;
        the rest of its contents are opaque to the coalescer and get handed
        to `transmit(data, live=...)` unchanged."""
        serial = data["serial"]
        if serial not in self._tasks:
            self._last_data[serial] = data
            await self._transmit(data, live=True)
            self._tasks[serial] = asyncio.create_task(self._run_serial(serial))
        else:
            self._pending[serial] = data

    async def _run_serial(self, serial: str) -> None:
        idle = 0
        try:
            while True:
                await asyncio.sleep(self._min)
                data = self._pending.pop(serial, None)
                if data is not None:
                    self._last_data[serial] = data
                    try:
                        await self._transmit(data, live=True)
                    except Exception:
                        log.exception("transmit failed for %s", serial)
                    idle = 0
                    continue
                idle += 1
                if idle >= self._idle_threshold:
                    if await self._run_eof(serial):
                        # EOF was interrupted by a new observation; resume.
                        idle = 0
                        continue
                    return
        finally:
            self._tasks.pop(serial, None)
            self._last_data.pop(serial, None)
            self._pending.pop(serial, None)

    async def _run_eof(self, serial: str) -> bool:
        """Emit redundant finals + killed-object, checking `_pending`
        between each step. Returns True if a new observation arrived mid-
        EOF (caller resumes the normal loop), False if EOF completed."""
        last = self._last_data.get(serial)
        if last is None:
            return False
        log.info("end-of-flight %s: %d final(s) + killed-object",
                 serial, self._final_redundancy)
        for i in range(self._final_redundancy):
            if i > 0 and self._final_spacing > 0:
                await asyncio.sleep(self._final_spacing)
                if serial in self._pending:
                    log.info("EOF %s aborted: new observation arrived", serial)
                    return True
            try:
                await self._transmit(last, live=True)
            except Exception:
                log.exception("final TX failed for %s", serial)
        if self._final_spacing > 0:
            await asyncio.sleep(self._final_spacing)
            if serial in self._pending:
                log.info("EOF %s aborted: new observation arrived", serial)
                return True
        try:
            await self._transmit(last, live=False)
        except Exception:
            log.exception("killed-object TX failed for %s", serial)
        return False

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        self._pending.clear()
        self._last_data.clear()


class KissTncClient:
    """Persistent TCP connection to Direwolf KISS, reconnects on write error."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    async def _open(self) -> None:
        log.info("Connecting to Direwolf KISS at %s:%d", self.host, self.port)
        _, self._writer = await asyncio.open_connection(self.host, self.port)

    async def _close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

    async def send(self, kiss_frame: bytes) -> bool:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._writer is None:
                        await self._open()
                    assert self._writer is not None
                    self._writer.write(kiss_frame)
                    await self._writer.drain()
                    return True
                except (ConnectionError, OSError) as e:
                    log.warning("KISS write failed (attempt %d): %s", attempt, e)
                    await self._close()
            log.error("KISS send dropped after retry")
            return False

    async def close(self) -> None:
        async with self._lock:
            await self._close()


class AprsPiGateway:
    def __init__(self, cfg: Config, kiss: KissTncClient,
                 now_fn=time.time):
        self.cfg = cfg
        self.kiss = kiss
        self._now = now_fn
        self.coalescer = LatestCoalescer(
            cfg.min_interval_sec,
            transmit=self._transmit,
            idle_window_threshold=cfg.idle_windows_before_eof,
            final_redundancy=cfg.final_redundancy,
            final_spacing_sec=cfg.final_spacing_sec,
        )

    def _extract(self, msg: dict) -> Optional[dict]:
        try:
            # auto_rx uses sentinel values when a sensor isn't providing
            # data — e.g. heading=-1, temp=-273, humidity/pressure/sats=-1.
            # Filter them so the corresponding comment tokens are skipped.
            data = {
                "serial": str(msg["callsign"]),
                "lat": float(msg["latitude"]),
                "lon": float(msg["longitude"]),
                "alt": float(msg["altitude"]),
                "frame": int(msg.get("frame", 0)),
                "snr": float(msg.get("snr", 0.0)),
                "freq_mhz": _parse_freq_mhz(msg.get("freq", "")),
                "model": str(msg.get("model", "")),
                "vel_v": _maybe_float(msg.get("vel_v")),
                "vel_h": _maybe_float(msg.get("vel_h")),
                "heading": _drop_if_negative(_maybe_float(msg.get("heading"))),
                # Coldest real upper-atmospheric temp is ~-90 C; -273 is the
                # absolute-zero sentinel auto_rx emits when no temp sensor.
                "temp": _drop_if_below(_maybe_float(msg.get("temp")), -100.0),
                "humidity": _drop_if_negative(_maybe_float(msg.get("humidity"))),
                "pressure": _drop_if_below_or_eq(_maybe_float(msg.get("pressure")), 0.0),
                "batt": _drop_if_below_or_eq(_maybe_float(msg.get("batt")), 0.0),
                "sats": _drop_if_negative(_maybe_int(msg.get("sats"))),
            }
            return data
        except (KeyError, ValueError, TypeError) as e:
            log.warning("dropping malformed PAYLOAD_SUMMARY: %s", e)
            return None

    async def on_payload_summary(self, msg: dict) -> None:
        data = self._extract(msg)
        if data is None:
            return
        await self.coalescer.new_observation(data)

    async def _transmit(self, data: dict, live: bool = True) -> None:
        comment = ae.format_sonde_comment(data)
        ts = datetime.fromtimestamp(self._now(), tz=timezone.utc)
        # Course (deg), speed (knots from m/s), and altitude (feet from
        # m, formatted by format_object_line) ride in standard APRS
        # extensions (CSE/SPD and /A=) so aprs.fi renders them natively.
        course = data.get("heading")
        vel_h_ms = data.get("vel_h")
        speed_knots = vel_h_ms * 1.94384 if vel_h_ms is not None else None
        info = ae.format_object_line(
            serial=data["serial"],
            lat=data["lat"],
            lon=data["lon"],
            ts_utc=ts,
            comment=comment,
            live=live,
            course_deg=course,
            speed_knots=speed_knots,
            altitude_m=data.get("alt"),
        )
        source = f"{self.cfg.callsign}-{GATEWAY_SSID}"
        frame = ae.build_ui_frame(
            source=source,
            dest=self.cfg.tocall,
            path=self.cfg.path,
            info=info,
        )
        wrapped = ae.kiss_wrap(frame)
        log.info("TX %s %s frame=%d -> %s: %s",
                 "killed" if not live else "object",
                 data["serial"], data.get("frame", 0), self.cfg.tocall, info)
        await self.kiss.send(wrapped)

def _parse_freq_mhz(freq) -> Optional[float]:
    """auto_rx emits freq as either a number or a string like '403.500 MHz'.
    Returns None for missing/unparseable/non-positive values."""
    if freq is None:
        return None
    if isinstance(freq, (int, float)):
        f = float(freq)
        return f if f > 0 else None
    s = str(freq).strip()
    if not s:
        return None
    s = s.split()[0]
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f > 0 else None


def _maybe_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _maybe_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _drop_if_negative(v):
    return None if v is not None and v < 0 else v


def _drop_if_below_or_eq(v, threshold: float):
    return None if v is not None and v <= threshold else v


def _drop_if_below(v, threshold: float):
    return None if v is not None and v < threshold else v


async def async_main(cfg: Config) -> int:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    kiss = KissTncClient(cfg.kiss_host, cfg.kiss_port)
    gateway = AprsPiGateway(cfg, kiss)

    async def on_msg(msg: dict) -> None:
        await gateway.on_payload_summary(msg)

    transport = await udp_listen(cfg.udp_port, on_msg)

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    log.info("aprs-backhaul-pi running (callsign=%s-%d, tocall=%s). Ctrl+C to stop.",
             cfg.callsign, GATEWAY_SSID, cfg.tocall)
    await stop_event.wait()
    log.info("Shutting down.")
    await gateway.coalescer.stop()
    transport.close()
    await kiss.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="APRS Backhaul Pi Gateway")
    parser.add_argument("--config", required=True, help="YAML config file")
    args = parser.parse_args()
    cfg = load_config(args.config)
    return asyncio.run(async_main(cfg))


if __name__ == "__main__":
    sys.exit(main())
