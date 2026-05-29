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
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, TextIO, Any

from gpp4323_lib import GPP4323

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


def measure(psu: GPP4323, channel: int, samples: int, delay: float) -> Measurement:
    """Average a few readings from a channel into one measurement."""
    vsum = isum = 0.0
    for i in range(samples):
        v, c, _ = psu.get_channel_load(channel=channel)
        vsum += v
        isum += c
        if i < samples - 1:
            time.sleep(delay)
    v = vsum / samples
    c = isum / samples
    return Measurement(v, c, v * c)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def prepare(psu: GPP4323, args: argparse.Namespace) -> None:
    """Put both channels into the modes this program uses: the input channel
    as a source, the load channel off. Outputs are enabled later per sweep."""
    psu.set_output(args.in_channel, False)
    psu.set_output(args.load_channel, False)
    psu.set_source_mode(args.in_channel)
    print(f"CH{args.in_channel} mode: {psu.get_mode(args.in_channel)} (input/source)")


def run_iq_sweep(psu: GPP4323, args: argparse.Namespace,
                 writer: Any) -> None:
    """Sweep input voltage with the output unloaded, recording input current."""
    print(f"\n=== Iq sweep: Vin {args.iq_vin} (no load) ===")
    inp, load = args.in_channel, args.load_channel

    # True no-load: take the load channel out of load mode and open its output.
    psu.set_load_cc(load, False)
    psu.set_output(load, False)

    psu.set_current(inp, args.input_ilimit)
    psu.set_voltage(inp, args.iq_vin_list[0])
    psu.set_output(inp, True)
    time.sleep(args.settle)

    for vin in args.iq_vin_list:
        psu.set_voltage(inp, vin)
        time.sleep(args.settle)
        m = measure(psu, inp, args.avg, args.avg_delay)
        iq_ma = m.current * 1000.0
        print(f"  Vin={vin:6.2f} V  ->  Vin_meas={m.voltage:6.3f} V  "
              f"Iq={iq_ma:8.3f} mA")
        writer.writerow({
            'test': 'iq', 'timestamp': now_iso(),
            'vin_set': f'{vin:.4f}', 'iload_set_a': '',
            'vin_meas': f'{m.voltage:.4f}', 'iin_meas_a': f'{m.current:.6f}',
            'pin_w': f'{m.power:.6f}',
            'vout_meas': '', 'iout_meas_a': '', 'pout_w': '',
            'efficiency': '', 'iq_ma': f'{iq_ma:.4f}',
        })


def run_efficiency_sweep(psu: GPP4323, args: argparse.Namespace,
                         writer: Any) -> None:
    """For each input voltage, sweep the output load current and record
    efficiency = Pout / Pin."""
    print(f"\n=== Efficiency: Vin {args.eff_vin}, loads {args.eff_loads} A ===")
    inp, load = args.in_channel, args.load_channel

    # Configure both channels with all outputs OFF, then energize. This is
    # safer (no live mode transitions) and avoids the GPP4323 constraint that a
    # channel won't switch into load mode while the other channel is sourcing.
    psu.set_output(inp, False)
    psu.set_output(load, False)
    psu.set_load_cc(load, True)
    print(f"  CH{load} mode: {psu.get_mode(load)}")
    psu.set_current(load, args.eff_loads_list[0])
    psu.set_current(inp, args.input_ilimit)
    psu.set_voltage(inp, args.eff_vin_list[0])

    # Everything configured; now energize and let the load run for the whole
    # sweep, varying only the sink current per point.
    psu.set_output(inp, True)
    psu.set_output(load, True)
    time.sleep(args.settle)

    for vin in args.eff_vin_list:
        psu.set_voltage(inp, vin)
        time.sleep(args.settle)
        for iload in args.eff_loads_list:
            psu.set_current(load, iload)
            time.sleep(args.settle)
            pin = measure(psu, inp, args.avg, args.avg_delay)
            pout = measure(psu, load, args.avg, args.avg_delay)
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


def safe_shutdown(psu: GPP4323, args: argparse.Namespace) -> None:
    """Leave the supply in a safe state: outputs off, load mode cleared."""
    try:
        psu.set_output(args.load_channel, False)
        psu.set_output(args.in_channel, False)
        psu.set_load_cc(args.load_channel, False)
        psu.set_voltage(args.in_channel, 0.0)
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
    parser.add_argument('--iq-vin', default='5:24:1',
                        help='Iq input-voltage sweep start:stop:step '
                             '(default: 5:24:1)')
    parser.add_argument('--eff-vin', default='6:18:2',
                        help='Efficiency family input voltages start:stop:step '
                             '(default: 6:18:2)')
    parser.add_argument('--eff-loads', default='0.01,0.03,0.1,0.3,1.0',
                        help='Efficiency load currents in amps, comma list '
                             '(default: 0.01,0.03,0.1,0.3,1.0)')
    parser.add_argument('--input-ilimit', type=float, default=2.0,
                        help='Source current limit on the input channel, A '
                             '(default: 2.0)')
    parser.add_argument('--settle', type=float, default=0.5,
                        help='Seconds to settle after a setpoint change '
                             '(default: 0.5)')
    parser.add_argument('--avg', type=int, default=3,
                        help='Readings averaged per measured point (default: 3)')
    parser.add_argument('--avg-delay', type=float, default=0.05,
                        help='Delay between averaged readings, s (default: 0.05)')
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

    psu = GPP4323(args.host, args.port)
    csvfile: Optional[TextIO] = None
    try:
        psu.connect()
        print(f"Instrument: {psu.get_idn()}")

        csvfile = open(args.output, 'w', newline='')
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()
        print(f"Writing to {args.output}")

        prepare(psu, args)

        if not args.skip_iq:
            run_iq_sweep(psu, args, writer)
        if not args.skip_efficiency:
            run_efficiency_sweep(psu, args, writer)

        print("\nDone.")
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
    finally:
        safe_shutdown(psu, args)
        psu.disconnect()
        if csvfile:
            csvfile.close()


if __name__ == '__main__':
    main()
