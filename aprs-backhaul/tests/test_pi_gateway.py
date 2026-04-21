import asyncio
from unittest.mock import AsyncMock

import pytest

from lib import aprs_encoding as ae
from helpers import parse_info
from pi.aprs_pi_gateway import (
    AprsPiGateway,
    Config,
    LatestCoalescer,
    _parse_freq_mhz,
)

# Use a small min_interval so the self-scheduling timer fires fast enough
# that the test suite completes in sub-second time.
WINDOW = 0.05
WAIT = WINDOW * 2.0


def make_msg(serial="S4310587", lat=40.05, lon=-105.25, alt=25310.0,
             frame=2345, snr=12.3, freq="403.000 MHz", model="RS41"):
    return {
        "callsign": serial,
        "latitude": lat,
        "longitude": lon,
        "altitude": alt,
        "frame": frame,
        "snr": snr,
        "freq": freq,
        "model": model,
    }


def make_cfg(min_interval=WINDOW, idle_windows_before_eof=1,
             final_redundancy=2, final_spacing_sec=0.0):
    return Config(
        callsign="KK7YBO", tocall="APZSDH", path=[],
        min_interval_sec=min_interval,
        idle_windows_before_eof=idle_windows_before_eof,
        final_redundancy=final_redundancy,
        final_spacing_sec=final_spacing_sec,
    )


async def test_coalescer_first_packet_transmits_immediately():
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx)
    await c.new_observation({"serial": "S1", "frame": 1})
    assert tx.await_count == 1
    assert tx.await_args.args[0]["frame"] == 1
    await c.stop()


async def test_coalescer_subsequent_buffered_not_transmitted_on_arrival():
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx)
    await c.new_observation({"serial": "S1", "frame": 1})
    await c.new_observation({"serial": "S1", "frame": 2})
    await c.new_observation({"serial": "S1", "frame": 3})
    assert tx.await_count == 1   # only the first-ever
    await c.stop()


async def test_coalescer_latest_flushed_after_window():
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx)
    await c.new_observation({"serial": "S1", "frame": 1})
    await c.new_observation({"serial": "S1", "frame": 2})
    await c.new_observation({"serial": "S1", "frame": 3})
    await asyncio.sleep(WAIT)
    assert tx.await_count == 2
    assert tx.await_args_list[1].args[0]["frame"] == 3
    await c.stop()


def _live_flags(tx_mock) -> list[bool]:
    return [call.kwargs.get("live") for call in tx_mock.await_args_list]


def _tx_data(tx_mock) -> list:
    return [call.args[0] for call in tx_mock.await_args_list]


async def test_coalescer_exits_after_idle_windows():
    """After `idle_window_threshold` windows with no data, EOF runs (just a
    killed-object, since last_data is the first obs already TXed) and the
    task exits."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=0, final_spacing_sec=0.0)
    await c.new_observation({"serial": "S1", "frame": 1})
    await asyncio.sleep(WINDOW * 3)
    # First TX (live), then EOF killed-object.
    assert _live_flags(tx) == [True, False]
    assert "S1" not in c._tasks
    await c.stop()


async def test_coalescer_end_of_flight_flushes_then_exits():
    """Last heard observation still goes out on the next timer tick."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=0, final_spacing_sec=0.0)
    await c.new_observation({"serial": "S1", "frame": 1})   # TX immediately
    await c.new_observation({"serial": "S1", "frame": 99})  # buffered
    # Sonde goes silent here.
    await asyncio.sleep(WINDOW * 4)
    # Expect: first live + flushed live (frame 99) + killed (frame 99).
    assert _live_flags(tx) == [True, True, False]
    assert _tx_data(tx)[1]["frame"] == 99
    assert _tx_data(tx)[2]["frame"] == 99
    assert "S1" not in c._tasks
    await c.stop()


async def test_coalescer_resumes_after_silence():
    """A new observation after the task has exited starts a fresh cycle."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=0, final_spacing_sec=0.0)
    await c.new_observation({"serial": "S1", "frame": 1})
    await asyncio.sleep(WINDOW * 3)     # EOF (killed) + task exits
    assert "S1" not in c._tasks
    await c.new_observation({"serial": "S1", "frame": 100})
    # Fresh cycle: TX live for frame 100.
    assert _live_flags(tx)[-1] is True
    assert _tx_data(tx)[-1]["frame"] == 100
    await c.stop()


async def test_coalescer_idle_threshold_counts_consecutive_silent_windows():
    """With idle_threshold=3, one quiet window then an observation resets the
    counter, so no EOF fires (no killed-object TX)."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=3,
                        final_redundancy=0, final_spacing_sec=0.0)
    await c.new_observation({"serial": "S1", "frame": 1})
    await asyncio.sleep(WAIT)                # 1 silent window
    await c.new_observation({"serial": "S1", "frame": 2})   # reset counter
    await asyncio.sleep(WAIT)                # pending flushed
    await c.new_observation({"serial": "S1", "frame": 3})   # reset counter
    assert False not in _live_flags(tx)   # no killed-object was emitted
    await c.stop()


async def test_coalescer_eof_redundant_finals_plus_killed():
    """With final_redundancy=2, EOF sends 2 live finals + 1 killed."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=2, final_spacing_sec=0.0)
    await c.new_observation({"serial": "S1", "frame": 1})
    await c.new_observation({"serial": "S1", "frame": 99})
    await asyncio.sleep(WAIT * 2)
    # Sequence: initial live + pending-flush live + 2 finals + 1 killed.
    assert _live_flags(tx) == [True, True, True, True, False]
    # All finals and the killed carry the last observation.
    assert _tx_data(tx)[-1]["frame"] == 99
    await c.stop()


async def test_coalescer_serials_independent():
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx)
    await c.new_observation({"serial": "A", "frame": 1})
    await c.new_observation({"serial": "B", "frame": 1})
    assert tx.await_count == 2
    await c.new_observation({"serial": "A", "frame": 2})
    await c.new_observation({"serial": "B", "frame": 2})
    await asyncio.sleep(WAIT)
    assert tx.await_count == 4
    serials_sent = {call.args[0]["frame"]: call.args[0] for call in tx.await_args_list}
    assert 1 in serials_sent and 2 in serials_sent
    await c.stop()


async def test_coalescer_stop_cancels_active_tasks():
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx)
    await c.new_observation({"serial": "S1", "frame": 1})
    await c.new_observation({"serial": "S2", "frame": 1})
    assert len(c._tasks) == 2
    await c.stop()
    assert len(c._tasks) == 0


def test_parse_freq_mhz_handles_string_and_number():
    assert _parse_freq_mhz("403.500 MHz") == 403.5
    assert _parse_freq_mhz("403.500") == 403.5
    assert _parse_freq_mhz(403.5) == 403.5
    # Missing/malformed/non-positive values now return None.
    assert _parse_freq_mhz("") is None
    assert _parse_freq_mhz(None) is None
    assert _parse_freq_mhz("garbage") is None
    assert _parse_freq_mhz(0) is None
    assert _parse_freq_mhz(-1.5) is None


async def test_gateway_first_packet_transmits_immediately():
    cfg = make_cfg()
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1_700_000_000.0)
    try:
        await gw.on_payload_summary(make_msg())
        assert kiss.send.await_count == 1

        sent_kiss = kiss.send.await_args[0][0]
        frames = ae.kiss_unframe(sent_kiss)
        source, dest, _path, info = ae.parse_ui_frame(frames[0])
        assert source == "KK7YBO-12"
        assert dest == "APZSDH"
        pkt = parse_info(info)
        comment = ae.parse_sonde_comment(pkt["comment"])
        assert comment.frame == 2345
    finally:
        await gw.coalescer.stop()


async def test_gateway_subsequent_within_window_buffered():
    cfg = make_cfg()
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1_700_000_000.0)
    try:
        await gw.on_payload_summary(make_msg(frame=1))
        await gw.on_payload_summary(make_msg(frame=2))
        await gw.on_payload_summary(make_msg(frame=3))
        assert kiss.send.await_count == 1
    finally:
        await gw.coalescer.stop()


async def test_gateway_latest_flushed_after_window():
    cfg = make_cfg()
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1_700_000_000.0)
    try:
        await gw.on_payload_summary(make_msg(frame=1))
        await gw.on_payload_summary(make_msg(frame=2))
        await gw.on_payload_summary(make_msg(frame=3))
        await asyncio.sleep(WAIT)
        assert kiss.send.await_count == 2
        second = kiss.send.await_args_list[1][0][0]
        info = ae.parse_ui_frame(ae.kiss_unframe(second)[0])[3]
        pkt = parse_info(info)
        assert ae.parse_sonde_comment(pkt["comment"]).frame == 3
    finally:
        await gw.coalescer.stop()


async def test_gateway_end_of_flight_emits_redundant_finals_plus_killed():
    """After idle threshold, gateway emits N live finals + 1 killed-object."""
    cfg = make_cfg(final_redundancy=2, final_spacing_sec=0.0,
                   idle_windows_before_eof=1)
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1_700_000_000.0)
    try:
        await gw.on_payload_summary(make_msg(frame=1))
        await gw.on_payload_summary(make_msg(frame=99, alt=500.0))
        # Wait for: flush window (TX frame 99) + idle window (EOF fires).
        await asyncio.sleep(WINDOW * 3)
        # Expect: first TX (frame 1 live) + flush TX (frame 99 live) +
        # 2 redundant final TXes (frame 99 live) + 1 killed (frame 99 dead)
        assert kiss.send.await_count == 5

        def parse(send_idx):
            kb = kiss.send.await_args_list[send_idx][0][0]
            info = ae.parse_ui_frame(ae.kiss_unframe(kb)[0])[3]
            return parse_info(info)

        obj0 = parse(0)
        assert obj0["alive"] is True and ae.parse_sonde_comment(obj0["comment"]).frame == 1

        obj1 = parse(1)
        assert obj1["alive"] is True and ae.parse_sonde_comment(obj1["comment"]).frame == 99

        obj2 = parse(2)
        assert obj2["alive"] is True and ae.parse_sonde_comment(obj2["comment"]).frame == 99

        obj3 = parse(3)
        assert obj3["alive"] is True and ae.parse_sonde_comment(obj3["comment"]).frame == 99

        obj4 = parse(4)
        assert obj4["alive"] is False and ae.parse_sonde_comment(obj4["comment"]).frame == 99
    finally:
        await gw.coalescer.stop()


async def test_coalescer_eof_no_op_when_no_last_data():
    """Defensive: if EOF is somehow reached with no last_data (task never
    saw a first observation — shouldn't happen in normal flow), the
    coalescer emits nothing."""
    tx = AsyncMock()
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=0, final_spacing_sec=0.0)
    # Directly invoke _run_eof with no recorded last_data.
    interrupted = await c._run_eof("never-seen")
    assert interrupted is False
    assert tx.await_count == 0


async def test_coalescer_resumes_normal_loop_when_obs_arrives_during_eof():
    """A new observation arriving during EOF's inter-packet sleep aborts EOF
    and resumes the normal loop. No killed-object is emitted."""
    tx = AsyncMock()
    # final_spacing=WINDOW gives us a real gap during EOF where we can
    # inject a new observation.
    c = LatestCoalescer(WINDOW, transmit=tx, idle_window_threshold=1,
                        final_redundancy=2, final_spacing_sec=WINDOW * 2)
    await c.new_observation({"serial": "S1", "frame": 1})
    # Wait for idle window (EOF starts) + one final TX + into the sleep.
    await asyncio.sleep(WINDOW * 2)
    # Interject during the final_spacing sleep.
    await c.new_observation({"serial": "S1", "frame": 99})
    # Give the coalescer time to abort, resume, and flush the new obs.
    await asyncio.sleep(WINDOW * 4)

    flags = _live_flags(tx)
    # EOF should NOT have completed — no live=False killed packet.
    assert False not in flags
    # And the new observation (frame 99) eventually TXed live.
    assert any(
        call.args[0].get("frame") == 99 and call.kwargs.get("live") is True
        for call in tx.await_args_list
    )
    await c.stop()


async def test_gateway_filters_autorx_sensor_sentinels():
    """auto_rx emits temp=-273, humidity/pressure/sats=-1, heading=-1
    when a sensor has no data. The gateway must skip those tokens rather
    than transmit nonsense."""
    cfg = make_cfg(idle_windows_before_eof=100)
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1_700_000_000.0)
    try:
        msg = make_msg()
        msg["temp"] = -273.0
        msg["humidity"] = -1
        msg["pressure"] = -1
        msg["batt"] = -1
        msg["sats"] = -1
        msg["heading"] = -1
        await gw.on_payload_summary(msg)
        info = ae.parse_ui_frame(ae.kiss_unframe(
            kiss.send.await_args[0][0]
        )[0])[3]
        # Strip the always-emitted /A= and !Wxx! extensions, then look at
        # the comment-internal tokens.
        pkt = parse_info(info)
        tokens = pkt["comment"].split()
        prefixes = {tok[0] for tok in tokens if tok}
        # All the sentinel-driven tokens should be absent.
        assert "T" not in prefixes
        assert "H" not in prefixes
        assert "P" not in prefixes
        assert "B" not in prefixes
        assert "N" not in prefixes
        assert "d" not in prefixes
        # Frame, snr, freq, type still present in the sub-comment.
        assert {"F", "S", "f", "t"}.issubset(prefixes)
        # And altitude landed in the standard /A= extension (parsed by aprslib).
        assert "altitude" in pkt
    finally:
        await gw.coalescer.stop()


async def test_gateway_drops_malformed_packet():
    cfg = make_cfg()
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1000.0)
    try:
        broken = make_msg()
        del broken["latitude"]
        await gw.on_payload_summary(broken)
        assert kiss.send.await_count == 0
    finally:
        await gw.coalescer.stop()


async def test_gateway_two_serials_both_fire_immediately():
    cfg = make_cfg()
    kiss = AsyncMock()
    kiss.send = AsyncMock(return_value=True)
    gw = AprsPiGateway(cfg, kiss, now_fn=lambda: 1000.0)
    try:
        await gw.on_payload_summary(make_msg(serial="A1234567"))
        await gw.on_payload_summary(make_msg(serial="B7654321"))
        assert kiss.send.await_count == 2
    finally:
        await gw.coalescer.stop()


def test_load_config_requires_callsign(tmp_path):
    from pi.aprs_pi_gateway import load_config
    p = tmp_path / "c.yaml"
    p.write_text("tocall: APZSDH\n")
    with pytest.raises(ValueError, match="callsign"):
        load_config(str(p))


def test_load_config_happy_path(tmp_path):
    from pi.aprs_pi_gateway import load_config
    p = tmp_path / "c.yaml"
    p.write_text("callsign: kk7ybo\npath: [WIDE2-1]\n")
    cfg = load_config(str(p))
    assert cfg.callsign == "KK7YBO"
    assert cfg.path == ["WIDE2-1"]
    assert cfg.tocall == "APZSDH"
