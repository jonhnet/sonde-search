"""APRS object packet formatting + AX.25 UI frame + KISS framing.

Encoders and matching parsers for the sonde-gateway APRS backhaul. The same
module is imported by both the pi (TX) and the cloud (RX) daemons so that
round-trip correctness is provable by unit tests.

Data is carried on the wire in three tiers, in descending order of "how
standard APRS clients will render this natively":

    1. Object-report fields (the packet header itself). Handled by every
       APRS client. See `format_object_line`.

           ;NNNNNNNNN*HHMMSSzDDMM.hhN/DDDMM.hhWO<extensions><comment>
            ^        ^^      ^       ^       ^ ^
            |        ||      |       |       | symbol code
            |        ||      |       |       symbol table
            |        ||      |       longitude (9 chars, W/E)
            |        ||      latitude (8 chars, N/S)
            |        |timestamp (7 chars, zulu)
            |        live/killed marker ('*' live, '_' killed)
            object name, 9 chars (serial, space-padded)

       Carries: sonde serial (object name), live/dead state, UTC timestamp,
       lat/lon (to ~18 m), balloon icon (symbol `/O`).

    2. Standard APRS comment extensions. Parsed by aprs.fi / aprslib and
       rendered as first-class fields ("Speed", "Altitude", etc.) rather
       than opaque comment text. Emitted by `format_object_line`:

         CSE/SPD   `nnn/nnn` immediately after the symbol code. Course
                   (deg) and speed (knots). 7 bytes.
         /A=       `/A=NNNNNN` (6-digit zero-padded feet) after CSE/SPD.
                   9 bytes when present.
         DAO       `!Wxy!` at the end of the comment. Adds one decimal
                   of precision each to lat and lon minutes, taking
                   position accuracy from ~18 m to ~2 m. 5 bytes,
                   always emitted.

       Carries: course, horizontal speed, altitude, ~10x position
       precision.

    3. Our private single-letter-code grammar in the remaining comment
       text — for the sonde telemetry fields that have no standard APRS
       equivalent. Format/parse is `format_sonde_comment` /
       `parse_sonde_comment`. aprs.fi shows these as comment text; the
       cloud daemon parses them back out. Tokens are space-separated
       and emitted in fixed order:

         F<frame>     S<snr>      f<freq_mhz>  t<type code>  v<vel_v>
         T<temp>      H<humidity> P<pressure>  B<batt>       N<sats>

       Sonde type codes are 1 char each (see `SONDE_TYPES`) so the cloud
       side can reconstruct an exact (manufacturer, type) pair for
       SondeHub — matching what auto_rx would have uploaded natively.

Fields not on the wire at all: `vel_h` and `heading` live in CSE/SPD
(tier 2), not in the private grammar; `alt_m` lives in `/A=` (tier 2).
The cloud handler re-attaches them to a SondeComment after aprslib
parses the incoming packet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

BALLOON_SYMBOL_TABLE = "/"
BALLOON_SYMBOL_CODE = "O"

# ---- Sonde type codes ----
#
# auto_rx's `model` field is encoded as a single character in the APRS
# comment ('t<code>'). The cloud side decodes back to both SondeHub's
# `manufacturer` and `type` fields.
#
# APPEND-ONLY — never reassign an existing code to a different type.
# Reception logs and historical packets depend on stable codes.
UNKNOWN_SONDE_CODE = "?"

# code -> (manufacturer_name, auto_rx `model` string)
#
# auto_rx overwrites telemetry["type"] with the variant subtype string
# (autorx/decode.py:1729 for RS41, etc.) so the values that hit the wire
# are the exact strings below. Each variant has its own code so the cloud
# side can forward an exact (manufacturer, type) pair to SondeHub —
# matching what SondeHub would have received from auto_rx natively.
#
# Codes are assigned sequentially within each manufacturer group. A-Z
# then a-z is plenty of room. Reorderable (and re-numberable) freely
# while pre-deployment.
SONDE_TYPES: dict[str, tuple[str, str]] = {
    # --- Vaisala ---
    "A": ("Vaisala", "RS41"),          # base / no subtype reported
    "B": ("Vaisala", "RS41-SG"),       # GPS, by far the most common
    "C": ("Vaisala", "RS41-SGP"),      # with pressure sensor
    "D": ("Vaisala", "RS41-SGM"),      # military (typically encrypted)
    "E": ("Vaisala", "RS41-SGPE"),     # extended
    "F": ("Vaisala", "RS92"),          # base / no subtype reported
    "G": ("Vaisala", "RS92-NGP"),      # 1680 MHz
    "H": ("Vaisala", "RS92-SGP"),
    "I": ("Vaisala", "RD41"),          # dropsonde
    "J": ("Vaisala", "RD94"),          # dropsonde
    # --- Graw ---
    "K": ("Graw", "DFM"),              # base / no subtype guess
    "L": ("Graw", "DFM06"),
    "M": ("Graw", "DFM09"),
    "N": ("Graw", "DFM09P"),
    "O": ("Graw", "DFM17"),
    "P": ("Graw", "DFM17P"),
    "Q": ("Graw", "DFM-Unknown"),      # explicit sentinel from sonde_specific.py
    # --- Meteomodem ---
    "R": ("Meteomodem", "M10"),
    "S": ("Meteomodem", "M20"),
    # --- Lockheed Martin ---
    "T": ("Lockheed Martin", "LMS6"),
    "U": ("Lockheed Martin", "MK2LMS"),
    # --- Intermet Systems ---
    "V": ("Intermet Systems", "IMET"),    # iMet-1 / iMet-4
    "W": ("Intermet Systems", "IMET5"),   # iMet-54
    # --- Meisei ---
    "X": ("Meisei", "MEISEI"),         # base / no subtype reported
    "Y": ("Meisei", "IMS100"),
    "Z": ("Meisei", "RS11G"),
    # --- Meteo-Radiy ---
    "a": ("Meteo-Radiy", "MRZ"),
    # --- WeatherX ---
    "b": ("WeatherX", "WXR301"),
    "c": ("WeatherX", "WXRPN9"),
    # --- Other ---
    "d": ("Other", "MTS01"),
    "e": ("Other", "PS15"),
}
_CODE_FOR_TYPE: dict[str, str] = {
    model.upper(): code for code, (_mfr, model) in SONDE_TYPES.items()
}


def encode_sonde_type(type_str: str) -> str:
    """Encode auto_rx's `model` string to a single-char APRS code.

    Returns '?' for an empty or unrecognised input.
    """
    if not type_str:
        return UNKNOWN_SONDE_CODE
    return _CODE_FOR_TYPE.get(type_str.upper(), UNKNOWN_SONDE_CODE)


def decode_sonde_type(code: str) -> tuple[str, str] | None:
    """Decode a single-char APRS code to (manufacturer_name, type_string).

    Returns None if the code isn't a recognised sonde type.
    """
    if not code or len(code) != 1:
        return None
    return SONDE_TYPES.get(code)


FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD

AX25_CONTROL_UI = 0x03
AX25_PID_NO_LAYER3 = 0xF0


def _ddm_with_dao(value: float, is_lat: bool) -> tuple[str, int]:
    """Encode `value` (signed degrees) as standard APRS DDM(M).hh{N|S|E|W}
    plus the third-decimal-of-minutes digit suitable for the APRS DAO
    extension.

    We must TRUNCATE rather than round to 2 decimals so the DAO digit
    (which is added on top by decoders) reconstructs to the original value.
    aprslib.util.latitude_to_ddm rounds, which would invalidate DAO; hence
    this local implementation.
    """
    hemi = ("N", "S") if is_lat else ("E", "W")
    deg_width = 2 if is_lat else 3
    a = abs(value)
    deg = int(a)
    min_full = (a - deg) * 60.0
    # round() compensates for IEEE-754 imprecision (e.g. 36.48 * 1000 may
    # come out as 36479.999...). The third digit is then the units of
    # min_micro % 10, the lower two decimals are min_micro // 10.
    min_micro = int(round(min_full * 1000))
    min_int_part = min_micro // 10            # e.g. 3648 (means 36.48)
    dao_digit = min_micro % 10                # e.g. 7
    direction = hemi[0] if value >= 0 else hemi[1]
    pos = (
        f"{deg:0{deg_width}d}"
        f"{min_int_part // 100:02d}.{min_int_part % 100:02d}"
        f"{direction}"
    )
    return pos, dao_digit


def _pack_object_name(serial: str) -> str:
    """9-char object name, space-padded. Truncate preserving the tail."""
    if len(serial) > 9:
        return serial[-9:]
    return serial.ljust(9)


def format_sonde_comment(data: dict) -> str:
    """Format the sonde-specific sub-comment from a normalized observation dict.

    Required keys: `frame`, `snr`.
    Optional keys: `freq_mhz`, `model`, `vel_v`, `temp`, `humidity`,
                   `pressure`, `batt`, `sats`. Skipped when None or missing.

    Note: `vel_h`/`heading` ride in the APRS CSE/SPD extension and `alt`
    rides in the APRS `/A=` extension — both assembled by
    `format_object_line`, not in this comment grammar.
    """
    tokens = [
        f"F{int(data['frame'])}",
        f"S{float(data['snr']):.1f}",
    ]
    freq = data.get("freq_mhz")
    if freq is not None:
        tokens.append(f"f{float(freq):.3f}")
    code = encode_sonde_type(data.get("model", ""))
    if code != UNKNOWN_SONDE_CODE:
        tokens.append(f"t{code}")
    v = data.get("vel_v")
    if v is not None:
        tokens.append(f"v{float(v):.1f}")
    v = data.get("temp")
    if v is not None:
        tokens.append(f"T{float(v):.1f}")
    v = data.get("humidity")
    if v is not None:
        tokens.append(f"H{int(round(float(v)))}")
    v = data.get("pressure")
    if v is not None:
        tokens.append(f"P{int(round(float(v)))}")
    v = data.get("batt")
    if v is not None:
        tokens.append(f"B{float(v):.1f}")
    v = data.get("sats")
    if v is not None:
        tokens.append(f"N{int(v)}")
    return " ".join(tokens)


@dataclass
class SondeComment:
    """Parsed contents of the sonde sub-comment.

    `vel_h`, `heading`, and `alt_m` are *not* parsed from the comment —
    they ride in standard APRS extensions (CSE/SPD and `/A=`). The cloud
    handler reads them from the aprslib-parsed `pkt` and attaches them to
    a SondeComment after the fact (see PacketHandler).
    """
    frame: int
    snr: float
    alt_m: int | None = None
    freq_mhz: float | None = None
    type_str: str | None = None
    manufacturer: str | None = None
    vel_v: float | None = None
    vel_h: float | None = None
    heading: int | None = None
    temp: float | None = None
    humidity: int | None = None
    pressure: int | None = None
    batt: float | None = None
    sats: int | None = None


def parse_sonde_comment(comment: str) -> SondeComment | None:
    frame = snr = None
    freq: float | None = None
    type_str: str | None = None
    manufacturer: str | None = None
    vel_v: float | None = None
    temp: float | None = None
    humidity: int | None = None
    pressure: int | None = None
    batt: float | None = None
    sats: int | None = None
    for tok in comment.strip().split():
        if not tok:
            continue
        prefix, rest = tok[0], tok[1:]
        try:
            if prefix == "F":
                frame = int(rest)
            elif prefix == "S":
                snr = float(rest)
            elif prefix == "f":
                freq = float(rest)
            elif prefix == "t":
                decoded = decode_sonde_type(rest)
                if decoded is not None:
                    manufacturer, type_str = decoded
            elif prefix == "v":
                vel_v = float(rest)
            elif prefix == "T":
                temp = float(rest)
            elif prefix == "H":
                humidity = int(rest)
            elif prefix == "P":
                pressure = int(rest)
            elif prefix == "B":
                batt = float(rest)
            elif prefix == "N":
                sats = int(rest)
            # Unknown prefixes (including legacy A/h/d from older packets)
            # are silently ignored. alt_m comes from the APRS /A= extension.
        except ValueError:
            return None
    if frame is None or snr is None:
        return None
    return SondeComment(
        frame=frame, snr=snr, freq_mhz=freq,
        type_str=type_str, manufacturer=manufacturer,
        vel_v=vel_v, temp=temp, humidity=humidity,
        pressure=pressure, batt=batt, sats=sats,
    )


def format_object_line(serial: str, lat: float, lon: float,
                       ts_utc: datetime, comment: str,
                       live: bool = True,
                       course_deg: int | None = None,
                       speed_knots: float | None = None,
                       altitude_m: float | None = None) -> str:
    """Build an APRS object info-field.

    Standard APRS extensions emitted (each parsed natively by aprs.fi /
    aprslib):
      - CSE/SPD (`nnn/nnn`, 7 bytes between symbol and comment) — when
        both `course_deg` and `speed_knots` are provided.
      - Altitude (`/A=NNNNNN` in the comment, 6-digit zero-padded feet)
        — when `altitude_m` is provided.
      - DAO precision (`!Wxy!` at the end of the comment, 5 bytes) —
        always emitted; gives ~10x lat/lon precision (~1.85 m at the
        equator) at near-zero cost.
    """
    if ts_utc.tzinfo is None:
        raise ValueError("ts_utc must be timezone-aware")
    ts_utc = ts_utc.astimezone(timezone.utc)

    lat_str, lat_dao = _ddm_with_dao(lat, is_lat=True)
    lon_str, lon_dao = _ddm_with_dao(lon, is_lat=False)

    cse_spd = ""
    if course_deg is not None and speed_knots is not None:
        cse_spd = (
            f"{int(round(course_deg)) % 360:03d}"
            "/"
            f"{min(999, max(0, int(round(speed_knots)))):03d}"
        )

    alt_ext = ""
    if altitude_m is not None:
        # APRS spec: 6-digit zero-padded feet, or '-' + 5 digits for negative.
        feet = int(round(altitude_m * 3.28084))
        if feet >= 0:
            alt_ext = f"/A={min(999999, feet):06d}"
        else:
            alt_ext = f"/A=-{min(99999, -feet):05d}"

    dao_ext = f"!W{lat_dao}{lon_dao}!"

    # Layout (per APRS convention used by Kenwood TH-D74, OpenTracker, etc.):
    #   ;NAME *TIMEzLAT/LONsym  CSE/SPD  /A=NNNNNN  <comment>  !Wxy!
    # CSE/SPD and /A= sit immediately after the symbol so positional
    # parsers find them; DAO goes at the end of the comment.
    return (
        ";"
        f"{_pack_object_name(serial)}"
        f"{'*' if live else '_'}"
        f"{ts_utc.strftime('%H%M%S')}z"
        f"{lat_str}"
        f"{BALLOON_SYMBOL_TABLE}"
        f"{lon_str}"
        f"{BALLOON_SYMBOL_CODE}"
        f"{cse_spd}"
        f"{alt_ext}"
        f"{comment}"
        f"{dao_ext}"
    )


def encode_callsign(callsign: str, ssid: int, last: bool) -> bytes:
    if not (0 <= ssid <= 15):
        raise ValueError(f"ssid out of range: {ssid}")
    cs = callsign.upper()
    if not re.fullmatch(r"[A-Z0-9]{1,6}", cs):
        raise ValueError(f"bad callsign: {callsign!r}")
    padded = cs.ljust(6)
    body = bytes((c << 1) & 0xFF for c in padded.encode("ascii"))
    ssid_byte = 0x60 | (ssid << 1) | (0x01 if last else 0x00)
    return body + bytes([ssid_byte])


def _parse_address(sep: str) -> tuple[str, int]:
    """Parse 'N0CALL-10' → ('N0CALL', 10); 'APZSDH' → ('APZSDH', 0)."""
    if "-" in sep:
        base, _, ssid = sep.partition("-")
        return base, int(ssid)
    return sep, 0


def build_ui_frame(source: str, dest: str, path: list[str], info: str) -> bytes:
    src_call, src_ssid = _parse_address(source)
    dst_call, dst_ssid = _parse_address(dest)

    addresses: list[bytes] = []
    is_last = (len(path) == 0)
    addresses.append(encode_callsign(dst_call, dst_ssid, last=False))
    addresses.append(encode_callsign(src_call, src_ssid, last=is_last))
    for i, hop in enumerate(path):
        call, ssid = _parse_address(hop)
        addresses.append(encode_callsign(call, ssid, last=(i == len(path) - 1)))

    frame = b"".join(addresses)
    frame += bytes([AX25_CONTROL_UI, AX25_PID_NO_LAYER3])
    frame += info.encode("ascii", errors="replace")
    return frame


def kiss_escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == FEND:
            out.extend((FESC, TFEND))
        elif b == FESC:
            out.extend((FESC, TFESC))
        else:
            out.append(b)
    return bytes(out)


def kiss_unescape(data: bytes) -> bytes:
    out = bytearray()
    it = iter(data)
    for b in it:
        if b == FESC:
            nxt = next(it, None)
            if nxt == TFEND:
                out.append(FEND)
            elif nxt == TFESC:
                out.append(FESC)
            else:
                raise ValueError(f"bad KISS escape sequence: FESC {nxt!r}")
        else:
            out.append(b)
    return bytes(out)


def kiss_wrap(ax25_frame: bytes, port: int = 0) -> bytes:
    cmd_byte = ((port & 0x0F) << 4) | 0x00  # data frame
    return bytes([FEND, cmd_byte]) + kiss_escape(ax25_frame) + bytes([FEND])


def kiss_unframe(stream: bytes) -> list[bytes]:
    """Split a KISS byte stream into a list of decoded AX.25 frames.

    Drops the leading command byte from each frame. Empty frames (adjacent
    FENDs, a common idle-marker pattern) are skipped.
    """
    frames: list[bytes] = []
    parts = stream.split(bytes([FEND]))
    for part in parts:
        if not part:
            continue
        body = part[1:]
        if not body:
            continue
        frames.append(kiss_unescape(body))
    return frames


def decode_callsign(addr: bytes) -> tuple[str, int, bool]:
    """Inverse of `encode_callsign`. Returns (call, ssid, last_bit)."""
    if len(addr) != 7:
        raise ValueError(f"address must be 7 bytes, got {len(addr)}")
    chars = bytes((b >> 1) & 0x7F for b in addr[:6]).decode("ascii").rstrip()
    ssid_byte = addr[6]
    ssid = (ssid_byte >> 1) & 0x0F
    last = bool(ssid_byte & 0x01)
    return chars, ssid, last


def parse_ui_frame(frame: bytes) -> tuple[str, str, list[str], str] | None:
    """Parse an AX.25 UI frame → (source, dest, path, info).

    Returns None if the frame is malformed or isn't a UI I-frame.
    """
    if len(frame) < 16:
        return None
    addresses: list[tuple[str, int, bool]] = []
    i = 0
    while i + 7 <= len(frame):
        addr = decode_callsign(frame[i:i + 7])
        addresses.append(addr)
        i += 7
        if addr[2]:
            break
    else:
        return None
    if len(addresses) < 2:
        return None
    if i + 2 > len(frame):
        return None
    if frame[i] != AX25_CONTROL_UI or frame[i + 1] != AX25_PID_NO_LAYER3:
        return None
    info = frame[i + 2:].decode("ascii", errors="replace")

    def fmt(a: tuple[str, int, bool]) -> str:
        return f"{a[0]}-{a[1]}" if a[1] else a[0]

    dest = fmt(addresses[0])
    source = fmt(addresses[1])
    path = [fmt(a) for a in addresses[2:]]
    return source, dest, path, info
