#!/usr/bin/env python3
"""
Mock radiosonde_auto_rx UDP sender.

Simulates auto_rx by sending JSON telemetry packets on the same UDP port
that auto_rx uses (default 55673). Can either generate a simulated
descending sonde or replay a real auto_rx CSV log file.

Usage:
    # Simulated sonde
    ./mock_autorx.py [--port 55673] [--interval 2.0] [--num-sondes 1]

    # Replay a log file
    ./mock_autorx.py --replay /path/to/20240315-120530_U3450553_RS41_404800_sonde.log
"""

import argparse
import csv
import json
import math
import socket
import time
from datetime import datetime, timezone


def make_sonde(index):
    """Create initial state for a simulated sonde."""
    return {
        "serial": f"S43105{87 + index:02d}",
        "type": ["RS41", "DFM17", "M20", "RS92"][index % 4],
        "freq_mhz": 403.0 + index * 0.4,
        "lat": 40.05 + index * 0.02,
        "lon": -105.25 + index * 0.03,
        "alt": 25000.0 + index * 2000,
        "step": 0,
    }


def step_sonde(s):
    """Advance a sonde's position by one time step, return an auto_rx-format dict."""
    s["step"] += 1
    step = s["step"]

    alt = s["alt"]
    wind_speed = 6.0 + 4.0 * math.sin(step * 0.05) + (alt / 10000.0)
    wind_heading = 240.0 + 30.0 * math.sin(step * 0.02)

    if alt > 20000:
        descent_rate = -3.0
    elif alt > 10000:
        descent_rate = -5.0
    else:
        descent_rate = -6.5

    heading_rad = math.radians(wind_heading)
    dlat = wind_speed * math.cos(heading_rad) / 111320.0
    dlon = wind_speed * math.sin(heading_rad) / (111320.0 * math.cos(math.radians(s["lat"])))

    s["lat"] += dlat
    s["lon"] += dlon
    s["alt"] += descent_rate

    if s["alt"] < 0:
        s["alt"] = 0

    snr = max(0.0, 12.0 - (25000 - s["alt"]) / 4000.0)

    now_utc = datetime.now(timezone.utc)
    return {
        "type": "PAYLOAD_SUMMARY",
        "station": "MOCK",
        "callsign": s["serial"],
        "model": s["type"],
        "freq": f'{s["freq_mhz"]:.3f} MHz',
        "latitude": round(s["lat"], 6),
        "longitude": round(s["lon"], 6),
        "altitude": round(s["alt"], 1),
        "speed": round(wind_speed * 3.6, 1),
        "vel_h": round(wind_speed, 1),
        "heading": round(wind_heading, 1),
        "vel_v": round(descent_rate, 1),
        "time": now_utc.strftime("%H:%M:%S"),
        "comment": "Radiosonde",
        "snr": round(snr, 1),
        "temp": round(-60.0 + s["alt"] / 1000.0, 1),
        "humidity": 1.8,
        "sats": 10,
        "batt": 2.6,
        "frame": s["step"],
    }


def csv_row_to_payload_summary(row, station="REPLAY"):
    """Convert an auto_rx CSV log row to a PAYLOAD_SUMMARY JSON dict.

    auto_rx CSV columns:
    timestamp,serial,frame,lat,lon,alt,vel_v,vel_h,heading,temp,humidity,
    pressure,type,freq_mhz,snr,f_error_hz,sats,batt_v,burst_timer,aux_data
    """
    # Parse the timestamp to extract HH:MM:SS
    ts_str = row["timestamp"]
    try:
        dt = datetime.fromisoformat(ts_str)
        time_str = dt.strftime("%H:%M:%S")
    except ValueError:
        time_str = ts_str[-8:] if len(ts_str) >= 8 else "00:00:00"

    freq_mhz = float(row.get("freq_mhz", 0))

    return {
        "type": "PAYLOAD_SUMMARY",
        "station": station,
        "callsign": row["serial"],
        "model": row.get("type", "Unknown"),
        "freq": f"{freq_mhz:.4f} MHz",
        "latitude": float(row["lat"]),
        "longitude": float(row["lon"]),
        "altitude": float(row["alt"]),
        "speed": float(row.get("vel_h", 0)) * 3.6,
        "vel_h": float(row.get("vel_h", 0)),
        "heading": float(row.get("heading", 0)),
        "vel_v": float(row.get("vel_v", 0)),
        "time": time_str,
        "comment": "Radiosonde",
        "snr": float(row.get("snr", -99)),
        "temp": float(row.get("temp", -273)),
        "humidity": float(row.get("humidity", -1)),
        "sats": int(row.get("sats", -1)),
        "batt": float(row.get("batt_v", -1)),
        "frame": int(row.get("frame", 0)),
    }


def replay_log(args):
    """Replay an auto_rx CSV log file as UDP packets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"Replaying {args.replay} to {args.host}:{args.port} every {args.interval}s")
    print()

    try:
        with open(args.replay, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                msg = csv_row_to_payload_summary(row)
                payload = json.dumps(msg).encode("utf-8")
                sock.sendto(payload, (args.host, args.port))

                print(
                    f"  {msg['callsign']} ({msg['model']}) "
                    f"{msg['freq']} "
                    f"alt={msg['altitude']:>8.1f}m "
                    f"vel_v={msg['vel_v']:>5.1f}m/s "
                    f"snr={msg['snr']:>4.1f} "
                    f"({msg['latitude']:.4f}, {msg['longitude']:.4f})"
                )

                time.sleep(args.interval)

        print("\nReplay complete!")

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


def simulate(args):
    """Run the simulated sonde generator."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sondes = [make_sonde(i) for i in range(args.num_sondes)]

    print(f"Mock auto_rx: sending to {args.host}:{args.port} every {args.interval}s")
    print(f"Simulating {args.num_sondes} sonde(s): {[s['serial'] for s in sondes]}")
    print()

    try:
        while True:
            for s in sondes:
                if s["alt"] <= 0:
                    continue

                msg = step_sonde(s)
                payload = json.dumps(msg).encode("utf-8")
                sock.sendto(payload, (args.host, args.port))

                print(
                    f"  {msg['callsign']} ({msg['model']}) "
                    f"{msg['freq']} "
                    f"alt={msg['altitude']:>8.1f}m "
                    f"vel_v={msg['vel_v']:>5.1f}m/s "
                    f"snr={msg['snr']:>4.1f} "
                    f"({msg['latitude']:.4f}, {msg['longitude']:.4f})"
                )

            if all(s["alt"] <= 0 for s in sondes):
                print("\nAll sondes have landed!")
                break

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(description="Mock radiosonde_auto_rx UDP sender")
    parser.add_argument("--port", type=int, default=55673, help="UDP port (default: 55673)")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Destination host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, help="Seconds between packets (default: 2.0)"
    )
    parser.add_argument(
        "--num-sondes", type=int, default=1, help="Number of simultaneous sondes (default: 1)"
    )
    parser.add_argument(
        "--replay", type=str, default=None,
        help="Path to an auto_rx CSV log file to replay instead of simulating"
    )
    args = parser.parse_args()

    if args.replay:
        replay_log(args)
    else:
        simulate(args)


if __name__ == "__main__":
    main()
