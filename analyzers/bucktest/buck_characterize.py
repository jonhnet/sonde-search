#!/usr/bin/env python3
"""
Buck-converter characterizer for the GW Instek GPP4323.

The buck converter's input is driven by one GPP4323 channel in source mode and
its 5 V output is loaded by a second channel in constant-current electronic-load
mode (CH1/CH2 only). The program walks two parameter spaces and writes every
measured point to a single CSV:

  iq:         no-load input (quiescent) current vs. input voltage
  efficiency: output/input power efficiency vs. load current, one curve per
              input voltage

Plot the result with buck_plot.py.
"""

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, TextIO

sys.path.insert(0, os.path.expanduser('~/projects/gpp4323'))
import gpp4323
sys.path.insert(0, os.path.expanduser('~/projects/dmm'))
import dmmlib

CSV_FIELDS = [
    'test', 'timestamp',
    'vin_set', 'iload_set_a',
    'vin_meas', 'iin_meas_a', 'pin_w',
    'vout_meas', 'iout_meas_a', 'pout_w',
    'efficiency', 'iq_ma',
]


def parse_range(spec: str) -> list[float]:
    """Parse 'start:stop:step' into an inclusive list of floats."""
    parts = spec.split(':')
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"range must be start:stop:step, got '{spec}'")
    start, stop, step = (float(p) for p in parts)
    if step <= 0:
        raise argparse.ArgumentTypeError("step must be positive")
    vals = []
    # Build inclusive of stop, tolerating float round-off on the last point.
    n = 0
    while True:
        v = start + n * step
        if v > stop + step * 1e-6:
            break
        vals.append(round(v, 6))
        n += 1
    return vals


def parse_list(spec: str) -> list[float]:
    """Parse a comma-separated list of floats."""
    return [float(x) for x in spec.split(',')]


@dataclass
class Measurement:
    voltage: float
    current: float
    power: float


def measure(g: gpp4323.GPP4323, channel: int,
            dmm: Optional[dmmlib.Keysight34465A] = None) -> Measurement:
    """One reading of a channel. Voltage comes from the GPP channel; current
    from the DMM (in series, integrating over its configured aperture) if
    given, else from the GPP channel."""
    d = g.meas().asDict()[channel]
    v = d['voltage']
    c = dmm.read() if dmm else d['current']
    return Measurement(v, c, v * c)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare(g: gpp4323.GPP4323, args: argparse.Namespace) -> None:
    """All outputs off before anything is configured or energized."""
    g.channel(args.in_channel).disable()
    g.channel(args.load_channel).disable()


def run_iq_sweep(g: gpp4323.GPP4323, dmm: Optional[dmmlib.Keysight34465A],
                 args: argparse.Namespace, writer) -> None:
    """Sweep input voltage with the output unloaded, recording input current."""
    print(f"\n=== Iq sweep: Vin {args.iq_vin} (no load) ===")
    inp, load = args.in_channel, args.load_channel

    g.channel(load).disable()  # true no-load: output open
    inp_ch = g.channel(inp)
    inp_ch.set_source(args.iq_vin_list[0], args.input_ilimit)
    inp_ch.enable()
    time.sleep(args.settle)

    for vin in args.iq_vin_list:
        inp_ch.set_source(vin, args.input_ilimit)
        time.sleep(args.settle)
        m = measure(g, inp, dmm=dmm)
        iq_ma = m.current * 1000.0
        print(f"  Vin={vin:6.2f} V  ->  Vin_meas={m.voltage:6.3f} V  "
              f"Iq={iq_ma:10.6f} mA")
        writer.writerow({
            'test': 'iq', 'timestamp': now_iso(),
            'vin_set': f'{vin:.4f}', 'iload_set_a': '',
            'vin_meas': f'{m.voltage:.6f}', 'iin_meas_a': f'{m.current:.9f}',
            'pin_w': f'{m.power:.9f}',
            'vout_meas': '', 'iout_meas_a': '', 'pout_w': '',
            'efficiency': '', 'iq_ma': f'{iq_ma:.6f}',
        })


def run_efficiency_sweep(g: gpp4323.GPP4323, dmm: Optional[dmmlib.Keysight34465A],
                         args: argparse.Namespace, writer) -> None:
    """For each input voltage, sweep the output load current and record
    efficiency = Pout / Pin."""
    print(f"\n=== Efficiency: Vin {args.eff_vin}, loads {args.eff_loads} A ===")
    inp, load = args.in_channel, args.load_channel
    inp_ch, load_ch = g.channel(inp), g.channel(load)

    # Configure both channels with all outputs OFF, then energize. Safer (no
    # live mode transitions) and avoids the constraint that a channel won't
    # switch into load mode while the other channel is sourcing.
    inp_ch.disable()
    load_ch.disable()
    load_ch.set_load(cc=args.eff_loads_list[0])
    print(f"  CH{load} mode: {load_ch.get_mode()}")
    inp_ch.set_source(args.eff_vin_list[0], args.input_ilimit)

    inp_ch.enable()
    load_ch.enable()
    time.sleep(args.settle)

    for vin in args.eff_vin_list:
        inp_ch.set_source(vin, args.input_ilimit)
        time.sleep(args.settle)
        for iload in args.eff_loads_list:
            load_ch.set_load(cc=iload)
            time.sleep(args.settle)
            pin = measure(g, inp, dmm=dmm)
            pout = measure(g, load)
            eff = pout.power / pin.power if pin.power > 0 else 0.0
            print(f"  Vin={vin:6.2f} V  Iload={iload * 1000:7.1f} mA  ->  "
                  f"Pin={pin.power:6.3f} W  Pout={pout.power:6.3f} W  "
                  f"eff={eff * 100:5.1f}%")
            writer.writerow({
                'test': 'efficiency', 'timestamp': now_iso(),
                'vin_set': f'{vin:.4f}', 'iload_set_a': f'{iload:.4f}',
                'vin_meas': f'{pin.voltage:.4f}',
                'iin_meas_a': f'{pin.current:.6f}', 'pin_w': f'{pin.power:.6f}',
                'vout_meas': f'{pout.voltage:.4f}',
                'iout_meas_a': f'{pout.current:.6f}',
                'pout_w': f'{pout.power:.6f}',
                'efficiency': f'{eff:.6f}', 'iq_ma': '',
            })


def safe_shutdown(g: gpp4323.GPP4323, args: argparse.Namespace) -> None:
    """Leave the supply safe: both outputs off."""
    try:
        g.channel(args.load_channel).disable()
        g.channel(args.in_channel).disable()
    except Exception as e:  # best-effort cleanup
        print(f"Warning: shutdown command failed: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Characterize a buck converter (Iq and efficiency) '
                    'with a GPP4323.')
    parser.add_argument('--host', default='gpp4323',
                        help='GPP4323 hostname/IP (default: gpp4323)')
    parser.add_argument('--port', type=int, default=1026,
                        help='TCP port (default: 1026)')
    parser.add_argument('--in-channel', type=int, default=1,
                        help='Channel sourcing the buck input (default: 1)')
    parser.add_argument('--load-channel', type=int, default=2,
                        help='Channel loading the buck output, CC mode; '
                             'must be 1 or 2 (default: 2)')
    parser.add_argument('--iq-vin', default='6:18:1',
                        help='Iq input-voltage sweep start:stop:step '
                             '(default: 6:18:1)')
    parser.add_argument('--eff-vin', default='8:18:2',
                        help='Efficiency family input voltages start:stop:step '
                             '(default: 8:18:2)')
    parser.add_argument('--eff-loads', default='0.01,0.02,0.05,0.1,0.2,0.5,1.0',
                        help='Efficiency load currents in amps, comma list '
                             '(default: 0.01,0.02,0.05,0.1,0.2,0.5,1.0)')
    parser.add_argument('--dmm-host', default='dmm',
                        help='Measure input current with a Keysight 34465A DMM '
                             'at this host (wired in series with the buck '
                             'input) instead of the GPP4323 (default: dmm)')
    parser.add_argument('--input-ilimit', type=float, default=2.0,
                        help='Source current limit on the input channel, A '
                             '(default: 2.0)')
    parser.add_argument('--settle', type=float, default=2.0,
                        help='Seconds to settle after a setpoint change '
                             '(default: 2.0)')
    parser.add_argument('--dmm-aperture', type=float, default=0.5,
                        help='DMM integration aperture in seconds; one reading '
                             'is taken per point (default: 0.5)')
    parser.add_argument('--output', '-o', default='buck_data.csv',
                        help='Output CSV file (default: buck_data.csv)')
    parser.add_argument('--skip-iq', action='store_true',
                        help='Skip the Iq sweep')
    parser.add_argument('--skip-efficiency', action='store_true',
                        help='Skip the efficiency sweep')
    args = parser.parse_args()

    if args.load_channel not in (1, 2):
        parser.error('--load-channel must be 1 or 2 (load mode is CH1/CH2 only)')

    # Expand sweep specs once, up front.
    args.iq_vin_list = parse_range(args.iq_vin)
    args.eff_vin_list = parse_range(args.eff_vin)
    args.eff_loads_list = parse_list(args.eff_loads)

    g = None
    csvfile: Optional[TextIO] = None
    try:
        g = gpp4323.GPP4323(host=(args.host, args.port))
        dmm = dmmlib.Keysight34465A(args.dmm_host) if args.dmm_host else None
        if dmm:
            dmm.configure_dc_current(aperture=args.dmm_aperture)
            print(f"Measuring input current with DMM at {args.dmm_host} "
                  f"({args.dmm_aperture * 1000:.0f} ms aperture)")

        csvfile = open(args.output, 'w', newline='')
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()
        print(f"Writing to {args.output}")

        prepare(g, args)

        if not args.skip_iq:
            run_iq_sweep(g, dmm, args, writer)
        if not args.skip_efficiency:
            run_efficiency_sweep(g, dmm, args, writer)

        print("\nDone.")
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
    finally:
        if g is not None:
            safe_shutdown(g, args)
        if csvfile:
            csvfile.close()


if __name__ == '__main__':
    main()
