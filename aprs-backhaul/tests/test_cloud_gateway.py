import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from cloud.aprs_cloud_gateway import (
    CloudConfig,
    FrameDedup,
    PacketHandler,
    ReceptionLogger,
    SondeHubUploader,
    VERSION,
    build_sondehub_record,
    derive_uploader_callsign,
    load_cloud_config,
)
from lib import aprs_encoding as ae


def make_cfg(**overrides) -> CloudConfig:
    base = dict(
        aprsis_callsign="N0CALL",
        reception_log_path="/tmp/unused-in-unit-tests.jsonl",
        aprsis_passcode=-1,
        tocall="APZSDH",
        aprsis_filter="u/APZSDH",
        uploader_callsign_suffix="_APRS",
    )
    base.update(overrides)
    return CloudConfig(**base)


def make_pkt(**overrides):
    base = {
        "format": "object",
        "from": "KK7YBO-10",
        "to": "APZSDH",
        "object_name": "S4310587 ",
        "latitude": 40.05,
        "longitude": -105.25,
        "altitude": 25310.0,                    # parsed by aprslib from /A=
        "comment": "F2345 S12.3 f403.000 tRS41",
        "raw_timestamp": "181530z",
        "symbol": "O",
        "symbol_table": "/",
        "path": ["WIDE1-1"],
        "raw": "KK7YBO-10>APZSDH,WIDE1-1:;...",
        "alive": True,
    }
    base.update(overrides)
    return base


def test_derive_uploader_callsign_basic():
    assert derive_uploader_callsign("N3UUO-10") == "N3UUO_APRS"
    assert derive_uploader_callsign("N3UUO") == "N3UUO_APRS"
    assert derive_uploader_callsign("kk7ybo-1") == "KK7YBO_APRS"


def test_derive_uploader_callsign_custom_suffix():
    assert derive_uploader_callsign("N3UUO-10", "-APRS") == "N3UUO-APRS"
    assert derive_uploader_callsign("N3UUO-10", "") == "N3UUO"


def test_derive_uploader_callsign_empty_returns_none():
    assert derive_uploader_callsign("") is None
    assert derive_uploader_callsign("-10") is None


def test_frame_dedup_basic():
    now = {"t": 0.0}
    dedup = FrameDedup(ttl_sec=3600, now_fn=lambda: now["t"])
    assert dedup.should_upload("S1", 1) is True
    assert dedup.should_upload("S1", 1) is False
    assert dedup.should_upload("S1", 2) is True
    assert dedup.should_upload("S2", 1) is True


def test_frame_dedup_ttl_expiry():
    now = {"t": 0.0}
    dedup = FrameDedup(ttl_sec=60, now_fn=lambda: now["t"])
    dedup.should_upload("S1", 1)
    now["t"] = 61.0
    assert dedup.should_upload("S1", 1) is True


def test_build_sondehub_record_has_required_fields():
    cfg = make_cfg()
    comment = ae.SondeComment(frame=2345, snr=12.3, freq_mhz=403.000,
                              alt_m=25310, type_str="RS41",
                              manufacturer="Vaisala")
    now = datetime(2026, 4, 19, 18, 15, 31, tzinfo=timezone.utc)
    rec = build_sondehub_record(cfg, "S4310587", 40.05, -105.25, comment,
                                "181530", uploader_callsign="N3UUO_APRS",
                                now_utc=now)
    required = {"software_name", "software_version", "uploader_callsign",
                "time_received", "datetime", "serial", "frame", "lat", "lon",
                "alt", "type", "manufacturer", "frequency", "snr"}
    assert required.issubset(rec.keys())
    assert rec["uploader_callsign"] == "N3UUO_APRS"
    assert rec["serial"] == "S4310587"
    assert rec["type"] == "RS41"
    assert rec["manufacturer"] == "Vaisala"
    assert rec["software_version"] == VERSION


def test_build_sondehub_record_includes_velocity_when_present():
    cfg = make_cfg()
    comment = ae.SondeComment(frame=2345, snr=12.3, freq_mhz=403.000,
                              alt_m=25310, type_str="RS41",
                              manufacturer="Vaisala",
                              vel_v=-5.2, vel_h=8.4)
    now = datetime(2026, 4, 19, 18, 15, 31, tzinfo=timezone.utc)
    rec = build_sondehub_record(cfg, "S4310587", 40.05, -105.25, comment,
                                "181530", uploader_callsign="X",
                                now_utc=now)
    assert rec["vel_v"] == -5.2
    assert rec["vel_h"] == 8.4


def test_build_sondehub_record_omits_velocity_when_missing():
    cfg = make_cfg()
    comment = ae.SondeComment(frame=1, snr=0.0, freq_mhz=400.0, alt_m=0,
                              type_str="RS41", manufacturer="Vaisala")
    rec = build_sondehub_record(cfg, "X1", 0.0, 0.0, comment, "000000",
                                uploader_callsign="X",
                                now_utc=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert "vel_v" not in rec
    assert "vel_h" not in rec


def test_reception_logger_writes_jsonl(tmp_path):
    p = tmp_path / "receptions.jsonl"
    logger = ReceptionLogger(str(p))
    logger.log({"serial": "A", "frame": 1})
    logger.log({"serial": "B", "frame": 2})
    logger.close()

    lines = p.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"serial": "A", "frame": 1}
    assert json.loads(lines[1]) == {"serial": "B", "frame": 2}


def test_reception_logger_creates_parent_dir(tmp_path):
    p = tmp_path / "subdir" / "a" / "receptions.jsonl"
    logger = ReceptionLogger(str(p))
    logger.log({"x": 1})
    logger.close()
    assert p.exists()


def test_packet_handler_reads_course_speed_from_aprs_extension(tmp_path):
    """vel_h and heading come from APRS CSE/SPD (parsed by aprslib),
    not from the comment. Cloud handler must populate them on the way to
    the SondeHub record."""
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600),
                            now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31,
                                                    tzinfo=timezone.utc))
    handler(make_pkt(course=332, speed=59.264))   # 32 knots → 59.264 km/h
    logger.close()
    record = uploader.add.call_args[0][0]
    assert record["heading"] == 332
    # 59.264 km/h / 3.6 ≈ 16.46 m/s
    assert abs(record["vel_h"] - 16.46) < 0.01


def test_packet_handler_logs_and_queues_when_upload_enabled(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    dedup = FrameDedup(ttl_sec=3600)
    handler = PacketHandler(cfg, logger, uploader, dedup,
                            now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31,
                                                    tzinfo=timezone.utc))
    handler(make_pkt(**{"from": "N3UUO-10"}))
    logger.close()

    # Upload happened and used the derived uploader_callsign.
    assert uploader.add.call_count == 1
    record = uploader.add.call_args[0][0]
    assert record["uploader_callsign"] == "N3UUO_APRS"

    # Log has exactly one record with APRS metadata attached.
    lines = (tmp_path / "rx.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["uploader_callsign"] == "N3UUO_APRS"
    assert logged["aprs_from"] == "N3UUO-10"
    assert logged["aprs_path"] == ["WIDE1-1"]
    assert "aprs_raw" in logged
    assert logged["alive"] is True


def test_packet_handler_logs_but_does_not_upload_when_uploader_is_none(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    dedup = FrameDedup(ttl_sec=3600)
    handler = PacketHandler(cfg, logger, uploader=None, dedup=dedup,
                            now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31,
                                                    tzinfo=timezone.utc))
    handler(make_pkt())
    logger.close()

    assert (tmp_path / "rx.jsonl").exists()
    lines = (tmp_path / "rx.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1


def test_packet_handler_logs_killed_object_with_alive_false(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    dedup = FrameDedup(ttl_sec=3600)
    handler = PacketHandler(cfg, logger, uploader=None, dedup=dedup,
                            now_fn=lambda: datetime(2026, 4, 19, 18, 15, 31,
                                                    tzinfo=timezone.utc))
    # First: a live object.
    handler(make_pkt())
    # Dedup will drop a duplicate-frame packet, so use a different frame here.
    handler(make_pkt(
        alive=False,
        comment="F2346 S12.3 f403.000 A25310 tRS41",
    ))
    logger.close()

    lines = (tmp_path / "rx.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["alive"] is True
    assert json.loads(lines[1])["alive"] is False


def test_packet_handler_ignores_non_object_packets(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600))
    handler(make_pkt(format="uncompressed"))
    logger.close()
    assert uploader.add.call_count == 0
    # No reception was logged, so the file was never opened.
    assert not (tmp_path / "rx.jsonl").exists()


def test_packet_handler_ignores_wrong_tocall(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600))
    handler(make_pkt(to="APOTHER"))
    assert uploader.add.call_count == 0


def test_packet_handler_dedups(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600))
    handler(make_pkt())
    handler(make_pkt())
    logger.close()
    assert uploader.add.call_count == 1
    lines = (tmp_path / "rx.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1


def test_packet_handler_drops_unparseable_comment(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600))
    handler(make_pkt(comment="junk without frame"))
    logger.close()
    assert uploader.add.call_count == 0


def test_packet_handler_drops_when_source_missing(tmp_path):
    cfg = make_cfg(reception_log_path=str(tmp_path / "rx.jsonl"))
    logger = ReceptionLogger(cfg.reception_log_path)
    uploader = MagicMock()
    handler = PacketHandler(cfg, logger, uploader, FrameDedup(3600))
    pkt = make_pkt()
    pkt["from"] = ""
    handler(pkt)
    assert uploader.add.call_count == 0


def test_uploader_flush_once_sends_gzipped_json(monkeypatch):
    cfg = make_cfg()
    session = MagicMock()
    response = MagicMock(status_code=200, text="")
    session.put = MagicMock(return_value=response)
    uploader = SondeHubUploader(cfg, session=session)
    uploader.add({"serial": "A", "frame": 1})
    uploader.add({"serial": "B", "frame": 2})
    n = uploader.flush_once()
    assert n == 2
    call = session.put.call_args
    assert call.kwargs["headers"]["Content-Encoding"] == "gzip"
    import gzip as _g
    body = _g.decompress(call.kwargs["data"])
    records = json.loads(body)
    assert [r["serial"] for r in records] == ["A", "B"]


def test_uploader_flush_empty_is_noop():
    cfg = make_cfg()
    session = MagicMock()
    uploader = SondeHubUploader(cfg, session=session)
    assert uploader.flush_once() == 0
    session.put.assert_not_called()


def test_uploader_4xx_drops_batch_no_retry(monkeypatch):
    cfg = make_cfg()
    session = MagicMock()
    response = MagicMock(status_code=422, text="bad schema")
    session.put = MagicMock(return_value=response)
    monkeypatch.setattr("cloud.aprs_cloud_gateway.time.sleep", lambda s: None)
    uploader = SondeHubUploader(cfg, session=session)
    uploader.add({"serial": "A", "frame": 1})
    uploader.flush_once()
    assert session.put.call_count == 1


def test_load_cloud_config_requires_reception_log_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("aprsis_callsign: N0CALL\n")
    with pytest.raises(ValueError, match="reception_log_path"):
        load_cloud_config(str(p))


def test_load_cloud_config_requires_aprsis_callsign(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("reception_log_path: /tmp/x.jsonl\n")
    with pytest.raises(ValueError, match="aprsis_callsign"):
        load_cloud_config(str(p))


def test_load_cloud_config_happy_path(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "aprsis_callsign: N0CALL\n"
        "reception_log_path: /tmp/rx.jsonl\n"
        "uploader_callsign_suffix: -APRS\n"
    )
    cfg = load_cloud_config(str(p))
    assert cfg.aprsis_callsign == "N0CALL"
    assert cfg.reception_log_path == "/tmp/rx.jsonl"
    assert cfg.uploader_callsign_suffix == "-APRS"
