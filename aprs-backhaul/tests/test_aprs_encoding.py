from datetime import datetime, timezone

import pytest

from lib import aprs_encoding as ae
from helpers import parse_info


def test_format_object_line_known_fixture():
    ts = datetime(2026, 4, 19, 18, 15, 30, tzinfo=timezone.utc)
    info = ae.format_object_line(
        serial="S4310587",
        lat=40.05,
        lon=-105.25,
        ts_utc=ts,
        comment="F123 S12.3 f403.000 tA",
    )
    # DAO is always emitted; both decimals here are 0 so DAO is "!W00!".
    assert info == ";S4310587 *181530z4003.00N/10515.00WOF123 S12.3 f403.000 tA!W00!"


def test_format_object_line_southern_eastern_hemisphere():
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    info = ae.format_object_line("M1234567", -33.5, 151.25, ts, "F1 S0.0 f403.000 tRS41")
    assert ";M1234567 *000000z3330.00S/15115.00E" in info


def test_object_line_roundtrip_via_aprslib():
    ts = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    comment_text = "F2345 S-3.1 f403.000 tA"
    info = ae.format_object_line("S4310587", 47.608, -122.335, ts, comment_text,
                                 altitude_m=25310)
    pkt = parse_info(info)
    assert pkt["format"] == "object"
    assert pkt["object_name"].strip() == "S4310587"
    assert pkt["alive"] is True
    # With DAO + truncated 2-dec encoding, decoded lat/lon get within
    # ~2 m at the equator. Using a tight tolerance to confirm DAO worked.
    assert pkt["latitude"] == pytest.approx(47.608, abs=0.0001)
    assert pkt["longitude"] == pytest.approx(-122.335, abs=0.0001)
    assert pkt["symbol_table"] == "/"
    assert pkt["symbol"] == "O"
    # /A= and !Wxx! are stripped by aprslib; only our sub-comment remains.
    assert pkt["comment"] == comment_text
    # Altitude round-trip (25310 m → 83038 ft → 25310.78... m).
    assert pkt["altitude"] == pytest.approx(25310, abs=1)


def test_format_object_line_emits_altitude_extension():
    ts = datetime(2026, 4, 19, 18, 15, 30, tzinfo=timezone.utc)
    info = ae.format_object_line("X", 0.0, 0.0, ts, "F1 S0.0",
                                 altitude_m=9144.0)  # 9144 m ≈ 30000 ft
    assert "/A=030000" in info
    pkt = parse_info(info)
    assert pkt["altitude"] == pytest.approx(9144.0, abs=0.5)


def test_format_object_line_emits_dao_for_subdecimal_precision():
    ts = datetime(2026, 4, 19, 0, 0, 0, tzinfo=timezone.utc)
    # lat = 47.6081234: minutes = 36.487404...; truncated "36.48" + dao=7.
    # lon = -122.3358:  minutes = 20.148;        truncated "20.14" + dao=8.
    info = ae.format_object_line("X", 47.6081234, -122.3358, ts, "F1 S0.0")
    assert "4736.48N" in info
    assert "12220.14W" in info
    assert "!W78!" in info


def _obs(**overrides) -> dict:
    """Helper: build a minimal observation dict for format_sonde_comment tests."""
    base = {"frame": 2345, "snr": 12.3, "freq_mhz": 403.000, "model": "RS41"}
    base.update(overrides)
    return base


def test_format_comment_budget():
    # alt is no longer in the comment (it's in /A=); same for vel_h/heading.
    c = ae.format_sonde_comment(_obs(frame=123456, snr=-12.3))
    assert c == "F123456 S-12.3 f403.000 tA"
    assert len(c) <= 43


def test_format_sonde_comment_with_vertical_velocity_only():
    """vel_h, heading, and alt no longer go in the comment."""
    c = ae.format_sonde_comment(_obs(vel_v=-5.2, vel_h=8.4, heading=45, alt=25310))
    assert c == "F2345 S12.3 f403.000 tA v-5.2"


def test_parse_sonde_comment_vel_v_roundtrip():
    c = ae.format_sonde_comment(_obs(vel_v=-5.2))
    p = ae.parse_sonde_comment(c)
    assert p is not None
    assert p.vel_v == -5.2
    # vel_h / heading / alt_m are not stored in the comment.
    assert p.vel_h is None
    assert p.heading is None
    assert p.alt_m is None


def test_format_sonde_comment_with_all_in_comment_fields():
    c = ae.format_sonde_comment(_obs(
        frame=99999, snr=-12.3, alt=35000,           # alt skipped (in /A=)
        vel_v=-40.0, vel_h=150.0, heading=45.2,      # vel_h/heading skipped
        temp=-42.5, humidity=95.3, pressure=250.7,
        batt=3.05, sats=10,
    ))
    assert c == ("F99999 S-12.3 f403.000 tA v-40.0 "
                 "T-42.5 H95 P251 B3.0 N10")


def test_parse_sonde_comment_in_comment_fields_roundtrip():
    c = ae.format_sonde_comment(_obs(
        vel_v=-5.2,
        temp=-42.5, humidity=95, pressure=251,
        batt=3.0, sats=10,
    ))
    p = ae.parse_sonde_comment(c)
    assert p is not None
    assert p.vel_v == -5.2
    assert p.temp == -42.5
    assert p.humidity == 95
    assert p.pressure == 251
    assert p.batt == 3.0
    assert p.sats == 10


def test_parse_sonde_comment_silently_ignores_legacy_d_h_tokens():
    """Old packets that still carry `d` and `h` tokens parse without error
    but the values aren't stored (vel_h/heading come from CSE/SPD now)."""
    p = ae.parse_sonde_comment("F1 S0.0 f403.000 A100 tA h8.4 d045")
    assert p is not None
    assert p.vel_h is None
    assert p.heading is None


def test_parse_sonde_comment_velocity_optional():
    p = ae.parse_sonde_comment("F1 S0.0 f403.000 A100 tRS41")
    assert p is not None
    assert p.vel_v is None
    assert p.vel_h is None


def test_sonde_type_codes_are_unique():
    codes = list(ae.SONDE_TYPES.keys())
    assert len(codes) == len(set(codes))
    models = [m for _mfr, m in ae.SONDE_TYPES.values()]
    assert len(models) == len(set(models))


@pytest.mark.parametrize("type_str", list({m for _mfr, m in ae.SONDE_TYPES.values()}))
def test_encode_decode_roundtrip_all_known_types(type_str):
    code = ae.encode_sonde_type(type_str)
    assert len(code) == 1
    mfr, decoded = ae.decode_sonde_type(code)
    assert decoded == type_str
    # Manufacturer returned by decode must match the table.
    expected_mfr = ae.SONDE_TYPES[code][0]
    assert mfr == expected_mfr


def test_encode_sonde_type_case_insensitive():
    assert ae.encode_sonde_type("rs41") == ae.encode_sonde_type("RS41")
    assert ae.encode_sonde_type("Dfm09") == ae.encode_sonde_type("DFM09")


def test_encode_sonde_type_distinguishes_all_variants():
    """Every distinct type string auto_rx may emit gets its own code, so
    the cloud daemon can forward an exact (manufacturer, type) to SondeHub
    — matching what auto_rx would have uploaded directly."""
    types = [
        "RS41", "RS41-SG", "RS41-SGP", "RS41-SGM", "RS41-SGPE",
        "RS92", "RS92-NGP", "RS92-SGP",
        "DFM", "DFM06", "DFM09", "DFM09P", "DFM17", "DFM17P", "DFM-Unknown",
    ]
    codes = {t: ae.encode_sonde_type(t) for t in types}
    assert "?" not in codes.values()
    assert len(set(codes.values())) == len(types)
    for typ, code in codes.items():
        decoded = ae.decode_sonde_type(code)
        assert decoded is not None
        assert decoded[1] == typ


def test_encode_sonde_type_case_insensitive_for_variants():
    assert ae.encode_sonde_type("rs41-sg") == ae.encode_sonde_type("RS41-SG")
    assert ae.encode_sonde_type("Rs92-NgP") == ae.encode_sonde_type("RS92-NGP")


def test_encode_sonde_type_unknown_returns_qmark():
    assert ae.encode_sonde_type("") == "?"
    assert ae.encode_sonde_type("MADEUP") == "?"


def test_decode_sonde_type_malformed_returns_none():
    assert ae.decode_sonde_type("") is None
    assert ae.decode_sonde_type("AB") is None
    assert ae.decode_sonde_type("?") is None
    assert ae.decode_sonde_type("~") is None   # unassigned char


def test_format_parse_comment_type_roundtrip():
    c = ae.format_sonde_comment(_obs(model="IMET5"))
    assert "tW" in c   # IMET5 maps to 'W'
    p = ae.parse_sonde_comment(c)
    assert p is not None
    assert p.type_str == "IMET5"
    assert p.manufacturer == "Intermet Systems"


def test_format_sonde_comment_omits_t_token_when_type_unknown():
    c = ae.format_sonde_comment(_obs(model="FOOBAR"))
    assert " t" not in c and not c.startswith("t") and "tA" not in c
    # Parses cleanly with no type info.
    p = ae.parse_sonde_comment(c)
    assert p is not None
    assert p.type_str is None
    assert p.manufacturer is None


def test_format_sonde_comment_omits_t_token_when_model_empty():
    c = ae.format_sonde_comment(_obs(model=""))
    # No 't' token whatsoever.
    assert not any(tok.startswith("t") for tok in c.split())


def test_parse_sonde_comment_stray_t_question_mark_is_ignored():
    # If a packet from elsewhere still carries 't?', we treat it as no type.
    p = ae.parse_sonde_comment("F1 S0.0 f403.000 A100 t?")
    assert p is not None
    assert p.type_str is None
    assert p.manufacturer is None


def test_format_object_line_with_cse_spd():
    """Course/speed are emitted as the standard APRS data extension
    (`CSE/SPD`, exactly 7 bytes) between symbol code and comment."""
    ts = datetime(2026, 4, 19, 18, 15, 30, tzinfo=timezone.utc)
    info = ae.format_object_line(
        serial="S4310587", lat=40.05, lon=-105.25, ts_utc=ts,
        comment="F1 S0.0 f403.000 A100 tA",
        course_deg=332, speed_knots=32.0,
    )
    # Header is 37 bytes; CSE/SPD is the next 7 bytes.
    assert info[37:44] == "332/032"
    # And aprslib parses it back into course/speed (km/h).
    pkt = parse_info(info)
    assert pkt["course"] == 332
    assert abs(pkt["speed"] - 32.0 * 1.852) < 0.001  # knots → km/h


def test_format_object_line_omits_cse_spd_when_either_missing():
    ts = datetime(2026, 4, 19, 0, 0, 0, tzinfo=timezone.utc)
    no_course = ae.format_object_line("X", 0.0, 0.0, ts, "F1 S0.0 A0",
                                      course_deg=None, speed_knots=10.0)
    no_speed = ae.format_object_line("X", 0.0, 0.0, ts, "F1 S0.0 A0",
                                     course_deg=180, speed_knots=None)
    # Without the extension, the comment starts immediately after symbol code.
    assert no_course[37:].startswith("F1 S0.0 A0")
    assert no_speed[37:].startswith("F1 S0.0 A0")


def test_format_object_line_killed():
    ts = datetime(2026, 4, 19, 18, 15, 30, tzinfo=timezone.utc)
    info = ae.format_object_line(
        serial="S4310587", lat=40.05, lon=-105.25, ts_utc=ts,
        comment="F123 S12.3 f403.000 A25310 tRS41", live=False,
    )
    assert info[10] == "_"
    pkt = parse_info(info)
    assert pkt["format"] == "object"
    assert pkt["alive"] is False


def test_parse_comment_roundtrip():
    c = ae.format_sonde_comment(_obs(freq_mhz=403.100))
    p = ae.parse_sonde_comment(c)
    assert p is not None
    assert p.frame == 2345
    assert p.snr == 12.3
    assert p.freq_mhz == 403.100
    # alt_m no longer comes from the comment.
    assert p.alt_m is None
    assert p.type_str == "RS41"


def test_parse_comment_negative_snr():
    p = ae.parse_sonde_comment("F1 S-12.3 f403.000 tRS41")
    assert p is not None
    assert p.snr == -12.3


def test_parse_comment_missing_required_returns_none():
    # Missing frame and SNR — can't be a valid comment.
    assert ae.parse_sonde_comment("f403.000 tRS41") is None
    assert ae.parse_sonde_comment("F1 f403.000 tRS41") is None
    assert ae.parse_sonde_comment("S1.0 f403.000 tRS41") is None


def test_object_name_truncation_preserves_tail():
    ts = datetime(2026, 4, 19, 0, 0, 0, tzinfo=timezone.utc)
    info = ae.format_object_line("TOOLONGSERIAL1234", 0.0, 0.0, ts, "")
    # tail is 'ERIAL1234' (last 9 chars)
    assert info[1:10] == "ERIAL1234"


def test_encode_callsign_n0call_no_ssid_not_last():
    out = ae.encode_callsign("N0CALL", 0, last=False)
    assert len(out) == 7
    # Each char shifted left by 1:
    # N=0x4E<<1=0x9C, 0=0x30<<1=0x60, C=0x43<<1=0x86, A=0x41<<1=0x82,
    # L=0x4C<<1=0x98, L=0x4C<<1=0x98
    assert out[:6] == bytes([0x9C, 0x60, 0x86, 0x82, 0x98, 0x98])
    # SSID byte: 0x60 | 0 | 0 = 0x60
    assert out[6] == 0x60


def test_encode_callsign_short_padded_with_spaces():
    out = ae.encode_callsign("K7X", 10, last=True)
    # Spaces pad to 6 bytes: 0x20<<1 = 0x40
    assert out[3:6] == bytes([0x40, 0x40, 0x40])
    # SSID byte: 0x60 | (10 << 1) | 1 = 0x60 | 0x14 | 0x01 = 0x75
    assert out[6] == 0x75


def test_encode_callsign_rejects_bad_input():
    with pytest.raises(ValueError):
        ae.encode_callsign("too-long", 0, last=False)
    with pytest.raises(ValueError):
        ae.encode_callsign("K7X", 16, last=False)


def test_kiss_escape_roundtrip():
    data = bytes([0x01, 0xC0, 0x02, 0xDB, 0x03, 0xC0, 0xDB])
    esc = ae.kiss_escape(data)
    assert ae.kiss_unescape(esc) == data


def test_kiss_wrap_starts_and_ends_with_fend():
    ax = bytes([0x11, 0x22])
    wrapped = ae.kiss_wrap(ax)
    assert wrapped[0] == 0xC0
    assert wrapped[-1] == 0xC0
    assert wrapped[1] == 0x00  # data, port 0


def test_kiss_unframe_extracts_frames():
    ax1 = bytes([0x11, 0x22, 0x33])
    ax2 = bytes([0xC0, 0xDB, 0x99])  # exercises escapes
    stream = ae.kiss_wrap(ax1) + ae.kiss_wrap(ax2)
    frames = ae.kiss_unframe(stream)
    assert frames == [ax1, ax2]


def test_build_and_parse_ui_frame():
    info_text = ";S4310587 *181530z4003.00N/10515.00WOF1 S0.0 f403.000 A100 tRS41"
    frame = ae.build_ui_frame(
        source="KK7YBO-10",
        dest="APZSDH",
        path=["WIDE1-1", "WIDE2-1"],
        info=info_text,
    )
    # Header = 4 addresses * 7 bytes + control + pid = 30
    assert len(frame) == 4 * 7 + 2 + len(info_text)
    parsed = ae.parse_ui_frame(frame)
    assert parsed is not None
    source, dest, path, info = parsed
    assert source == "KK7YBO-10"
    assert dest == "APZSDH"
    assert path == ["WIDE1-1", "WIDE2-1"]
    assert info == info_text


def test_build_ui_frame_last_bit_set_on_final_address():
    frame = ae.build_ui_frame("N0CALL", "APZSDH", [], info=";")
    # No digipeater path: source is the final address, last bit set
    assert frame[13] & 0x01 == 0x01    # source SSID byte
    assert frame[6] & 0x01 == 0x00     # dest SSID byte (not last)

    frame2 = ae.build_ui_frame("N0CALL", "APZSDH", ["WIDE1-1"], info=";")
    # With a path hop, the last bit moves to the hop's SSID byte
    assert frame2[13] & 0x01 == 0x00   # source no longer last
    assert frame2[20] & 0x01 == 0x01   # hop is last
