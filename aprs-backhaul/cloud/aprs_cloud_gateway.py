#!/usr/bin/env python3
"""APRS cloud-side gateway: APRS-IS → SondeHub.

Connects to the APRS-IS network, filters for packets with our custom tocall
(default APZSDH), parses each object packet, and uploads the telemetry to
SondeHub at https://api.v2.sondehub.org/sondes/telemetry (PUT).
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

# Allow running this file directly from cloud/ — add aprs-backhaul/ (the
# parent of cloud/) to sys.path so `from lib import ...` works without
# the caller having to set PYTHONPATH.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aprslib  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402

from lib import aprs_encoding as ae  # noqa: E402

log = logging.getLogger("aprs-backhaul-cloud")

VERSION = "0.1.0"
SOFTWARE_NAME = "sondesearch-aprs-backhaul"
SONDEHUB_TELEMETRY_URL = "https://api.v2.sondehub.org/sondes/telemetry"


@dataclass
class CloudConfig:
    aprsis_callsign: str
    reception_log_path: str
    aprsis_passcode: int = -1
    aprsis_host: str = "rotate.aprs2.net"
    aprsis_port: int = 14580
    aprsis_filter: str = "u/APZSDH"
    tocall: str = "APZSDH"
    # The uploader_callsign credited to SondeHub is derived per-packet from
    # the APRS source callsign (minus SSID) + this suffix.
    # e.g. "N3UUO-10" -> "N3UUO_APRS".
    uploader_callsign_suffix: str = "_APRS"
    uploader_position: list[float] | None = None
    uploader_antenna: str | None = None
    dedup_ttl_sec: int = 3600
    upload_batch_max: int = 20
    upload_interval_sec: float = 2.0
    log_level: str = "INFO"


def load_cloud_config(path: str) -> CloudConfig:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    aprsis_callsign = raw.get("aprsis_callsign")
    reception_log_path = raw.get("reception_log_path")
    if not aprsis_callsign:
        raise ValueError(f"{path}: `aprsis_callsign` is required")
    if not reception_log_path:
        raise ValueError(
            f"{path}: `reception_log_path` is required "
            "(JSONL file where every parsed reception is appended)"
        )
    pos = raw.get("uploader_position")
    if pos is not None:
        pos = [float(x) for x in pos]
        if len(pos) != 3:
            raise ValueError(f"{path}: `uploader_position` must be [lat, lon, alt]")
    return CloudConfig(
        aprsis_callsign=str(aprsis_callsign).upper(),
        reception_log_path=str(reception_log_path),
        aprsis_passcode=int(raw.get("aprsis_passcode", -1)),
        aprsis_host=str(raw.get("aprsis_host", "rotate.aprs2.net")),
        aprsis_port=int(raw.get("aprsis_port", 14580)),
        aprsis_filter=str(raw.get("aprsis_filter", "u/APZSDH")),
        tocall=str(raw.get("tocall", "APZSDH")).upper(),
        uploader_callsign_suffix=str(raw.get("uploader_callsign_suffix", "_APRS")),
        uploader_position=pos,
        uploader_antenna=raw.get("uploader_antenna"),
        dedup_ttl_sec=int(raw.get("dedup_ttl_sec", 3600)),
        upload_batch_max=int(raw.get("upload_batch_max", 20)),
        upload_interval_sec=float(raw.get("upload_interval_sec", 2.0)),
        log_level=str(raw.get("log_level", "INFO")).upper(),
    )


def derive_uploader_callsign(aprs_source: str, suffix: str = "_APRS") -> str | None:
    """Strip the SSID from an APRS source callsign and append the suffix.
    Returns None if the input is empty or has no callable part."""
    if not aprs_source:
        return None
    base = aprs_source.partition("-")[0].strip().upper()
    if not base:
        return None
    return f"{base}{suffix}"


class ReceptionLogger:
    """Append-only JSONL log of every reception we parse successfully."""

    def __init__(self, path: str):
        self.path = path
        self._f = None

    def open(self) -> None:
        from pathlib import Path
        Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "a", buffering=1)  # line-buffered

    def log(self, record: dict) -> None:
        if self._f is None:
            self.open()
        assert self._f is not None
        self._f.write(json.dumps(record, separators=(",", ":")) + "\n")

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None


class FrameDedup:
    def __init__(self, ttl_sec: int = 3600, now_fn=time.time):
        self._seen: dict[tuple[str, int], float] = {}
        self._ttl = ttl_sec
        self._now = now_fn

    def should_upload(self, serial: str, frame: int) -> bool:
        now = self._now()
        self._gc(now)
        key = (serial, frame)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True

    def _gc(self, now: float) -> None:
        cutoff = now - self._ttl
        dead = [k for k, t in self._seen.items() if t < cutoff]
        for k in dead:
            del self._seen[k]


class SondeHubUploader:
    """Background-batching uploader for SondeHub sonde telemetry.

    Uses PUT to /sondes/telemetry with a JSON array body. `add()` queues a
    record; a worker thread flushes in batches. Retries with backoff on 5xx.
    Safe to substitute in tests by calling `flush_once` directly.
    """

    def __init__(self, cfg: CloudConfig, session: Optional[requests.Session] = None,
                 now_fn=time.time):
        self._cfg = cfg
        self._session = session or requests.Session()
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._now = now_fn

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=5)
            self._worker = None

    def add(self, record: dict) -> None:
        with self._lock:
            self._queue.append(record)
        self._wake.set()

    def _drain(self, limit: int) -> list[dict]:
        with self._lock:
            take = self._queue[:limit]
            del self._queue[:limit]
            return take

    def flush_once(self) -> int:
        batch = self._drain(self._cfg.upload_batch_max)
        if not batch:
            return 0
        self._put_with_retry(batch)
        return len(batch)

    def _put_with_retry(self, batch: list[dict]) -> None:
        body = gzip.compress(json.dumps(batch).encode("utf-8"))
        headers = {
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "User-Agent": f"{SOFTWARE_NAME}/{VERSION}",
        }
        for attempt in range(1, 6):
            try:
                r = self._session.put(
                    SONDEHUB_TELEMETRY_URL, data=body, headers=headers, timeout=30,
                )
                if 200 <= r.status_code < 300:
                    log.info("uploaded %d telemetry records to SondeHub", len(batch))
                    return
                if 300 <= r.status_code < 500:
                    log.error("SondeHub rejected batch (%d): %s",
                              r.status_code, r.text[:500])
                    return
                log.warning("SondeHub 5xx %d (attempt %d): %s",
                            r.status_code, attempt, r.text[:200])
            except requests.RequestException as e:
                log.warning("SondeHub upload error (attempt %d): %s", attempt, e)
            time.sleep(min(2 ** attempt, 30))
        log.error("SondeHub upload failed after retries, dropping %d records", len(batch))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._cfg.upload_interval_sec)
            self._wake.clear()
            while self.flush_once() > 0:
                pass


def _format_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _hhmmss_to_datetime(hhmmss: str, now_utc: datetime | None = None) -> datetime:
    """Reconstruct a full UTC datetime from HHMMSS plus current UTC date.

    Mirrors the midnight-rollover logic in auto_rx_udp.enrich_time_epoch.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    t = datetime.strptime(hhmmss, "%H%M%S").replace(
        year=now_utc.year, month=now_utc.month, day=now_utc.day,
        tzinfo=timezone.utc,
    )
    if (t - now_utc).total_seconds() > 43200:
        t -= timedelta(days=1)
    return t


def build_sondehub_record(cfg: CloudConfig, serial: str, lat: float, lon: float,
                          comment: ae.SondeComment, hhmmss: str,
                          uploader_callsign: str,
                          now_utc: datetime | None = None) -> dict:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    sonde_dt = _hhmmss_to_datetime(hhmmss, now_utc=now_utc)
    record: dict = {
        "software_name": SOFTWARE_NAME,
        "software_version": VERSION,
        "uploader_callsign": uploader_callsign,
        "time_received": _format_iso_utc(now_utc),
        "datetime": _format_iso_utc(sonde_dt),
        "serial": serial,
        "frame": comment.frame,
        "lat": lat,
        "lon": lon,
        "alt": float(comment.alt_m),
        "snr": comment.snr,
    }
    if comment.freq_mhz is not None:
        record["frequency"] = comment.freq_mhz
    if comment.type_str is not None:
        record["type"] = comment.type_str
    if comment.manufacturer is not None:
        record["manufacturer"] = comment.manufacturer
    for key in ("vel_v", "vel_h", "heading", "temp", "humidity",
                "pressure", "batt", "sats"):
        val = getattr(comment, key, None)
        if val is not None:
            record[key] = val
    if cfg.uploader_position:
        record["uploader_position"] = cfg.uploader_position
    if cfg.uploader_antenna:
        record["uploader_antenna"] = cfg.uploader_antenna
    return record


class PacketHandler:
    """Parses aprslib packets, logs each reception locally, and optionally
    forwards telemetry to SondeHub."""

    def __init__(self, cfg: CloudConfig, logger: ReceptionLogger,
                 uploader: Optional[SondeHubUploader],
                 dedup: FrameDedup, now_fn=lambda: datetime.now(timezone.utc)):
        self.cfg = cfg
        self.logger = logger
        self.uploader = uploader
        self.dedup = dedup
        self._now = now_fn

    def __call__(self, pkt: dict) -> None:
        if pkt.get("format") != "object":
            return
        if pkt.get("to") != self.cfg.tocall:
            return
        serial = str(pkt.get("object_name", "")).strip()
        if not serial:
            return
        try:
            # Round to 6 decimal places to suppress IEEE-754 float-format
            # artefacts (e.g. -122.32699999999999) in the reception log
            # and SondeHub upload. APRS DDM with DAO precision is at most
            # ~0.00002 deg, so 6 decimals is well past the actual
            # information content.
            lat = round(float(pkt["latitude"]), 6)
            lon = round(float(pkt["longitude"]), 6)
        except (KeyError, ValueError, TypeError):
            log.warning("object %s missing lat/lon; dropping", serial)
            return
        comment = ae.parse_sonde_comment(str(pkt.get("comment", "")))
        if comment is None:
            log.warning("object %s unparseable comment: %r", serial, pkt.get("comment"))
            return
        # Course/speed live in CSE/SPD; altitude lives in /A= — both
        # parsed by aprslib. aprslib returns speed in km/h and altitude
        # in metres; we convert speed to m/s for SondeHub.
        if pkt.get("course") is not None:
            comment.heading = int(pkt["course"])
        if pkt.get("speed") is not None:
            comment.vel_h = float(pkt["speed"]) / 3.6
        if pkt.get("altitude") is not None:
            comment.alt_m = int(round(float(pkt["altitude"])))
        if comment.alt_m is None:
            log.warning("object %s missing altitude (no /A= extension); dropping",
                        serial)
            return
        if not self.dedup.should_upload(serial, comment.frame):
            return

        aprs_from = str(pkt.get("from", "")).strip()
        uploader_callsign = derive_uploader_callsign(
            aprs_from, self.cfg.uploader_callsign_suffix,
        )
        if uploader_callsign is None:
            log.warning("object %s: missing/invalid source callsign %r; dropping",
                        serial, aprs_from)
            return

        hhmmss = str(pkt.get("raw_timestamp", ""))[:6] or self._now().strftime("%H%M%S")
        record = build_sondehub_record(
            self.cfg, serial, lat, lon, comment, hhmmss,
            uploader_callsign=uploader_callsign, now_utc=self._now(),
        )

        log_record = dict(record)
        log_record["aprs_from"] = aprs_from
        log_record["aprs_path"] = pkt.get("path", [])
        log_record["aprs_raw"] = pkt.get("raw", "")
        log_record["alive"] = pkt.get("alive", True)
        self.logger.log(log_record)

        if self.uploader is not None:
            self.uploader.add(record)
            log.info("queued %s frame=%d lat=%.4f lon=%.4f uploader=%s",
                     serial, comment.frame, lat, lon, uploader_callsign)
        else:
            log.info("logged %s frame=%d lat=%.4f lon=%.4f uploader=%s (upload off)",
                     serial, comment.frame, lat, lon, uploader_callsign)


def _run_aprs_is(cfg: CloudConfig, on_packet) -> None:
    backoff = 1.0
    while True:
        try:
            log.info("connecting to APRS-IS %s:%d as %s (filter=%r)",
                     cfg.aprsis_host, cfg.aprsis_port, cfg.aprsis_callsign, cfg.aprsis_filter)
            conn = aprslib.IS(
                cfg.aprsis_callsign,
                passwd=str(cfg.aprsis_passcode),
                host=cfg.aprsis_host,
                port=cfg.aprsis_port,
            )
            conn.set_filter(cfg.aprsis_filter)
            conn.connect()
            backoff = 1.0

            def _wrap(pkt):
                try:
                    on_packet(pkt)
                except Exception:
                    log.exception("packet handler crashed on: %r", pkt)

            try:
                conn.consumer(_wrap, raw=False, blocking=True)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except (aprslib.exceptions.ConnectionError, aprslib.exceptions.ConnectionDrop,
                aprslib.exceptions.LoginError, OSError) as e:
            log.warning("APRS-IS disconnected: %s", e)
        except Exception:
            log.exception("APRS-IS loop crashed")
        log.info("reconnecting in %.1fs", backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 60.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="APRS Backhaul Cloud Gateway")
    parser.add_argument("--config", required=True, help="YAML config file")
    parser.add_argument(
        "--sondehub-upload", action="store_true",
        help="Forward parsed telemetry to SondeHub. Off by default; without "
             "this flag, receptions are only appended to the local reception log.",
    )
    args = parser.parse_args()
    cfg = load_cloud_config(args.config)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    reception_logger = ReceptionLogger(cfg.reception_log_path)
    reception_logger.open()

    uploader: Optional[SondeHubUploader] = None
    if args.sondehub_upload:
        uploader = SondeHubUploader(cfg)
        uploader.start()
        log.info("SondeHub upload ENABLED.")
    else:
        log.info("SondeHub upload DISABLED (pass --sondehub-upload to enable).")

    dedup = FrameDedup(cfg.dedup_ttl_sec)
    handler = PacketHandler(cfg, reception_logger, uploader, dedup)
    log.info("aprs-backhaul-cloud running (filter=%r, log=%s). Ctrl+C to stop.",
             cfg.aprsis_filter, cfg.reception_log_path)
    try:
        _run_aprs_is(cfg, handler)
    except KeyboardInterrupt:
        log.info("Ctrl-C received, shutting down.")
    finally:
        if uploader is not None:
            uploader.stop()
        reception_logger.close()
    log.info("Shutdown complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
