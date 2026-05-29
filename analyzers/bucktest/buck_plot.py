#!/usr/bin/env python3
"""
Plot buck-converter characterization data produced by buck_characterize.py.

Generates two Plotly charts:
  1. Quiescent current (Iq, mA) vs. input voltage.
  2. Efficiency (%) vs. output load current, one curve per input voltage.
"""

import argparse
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go


def plot_iq(df: pd.DataFrame) -> go.Figure:
    iq = df[df['test'] == 'iq'].sort_values('vin_set')
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=iq['vin_set'], y=iq['iq_ma'],
        mode='lines+markers', name='Iq',
    ))
    fig.update_layout(
        title='Buck Quiescent Current vs. Input Voltage',
        xaxis_title='Input voltage (V)',
        yaxis_title='Quiescent current Iq (mA)',
        template='plotly',
        hovermode='x unified',
    )
    return fig


def plot_efficiency(df: pd.DataFrame, min_load_ma: float = 0.0) -> go.Figure:
    eff = df[df['test'] == 'efficiency'].copy()
    # The supply can't resolve small input currents, so light-load efficiency
    # is unreliable; min_load_ma drops those points (by commanded load).
    eff = eff[eff['iload_set_a'] * 1000.0 >= min_load_ma]
    eff['iout_ma'] = eff['iout_meas_a'] * 1000.0
    eff['eff_pct'] = eff['efficiency'] * 100.0

    fig = go.Figure()
    for vin, grp in eff.groupby('vin_set'):
        grp = grp.sort_values('iload_set_a')
        fig.add_trace(go.Scatter(
            x=grp['iout_ma'], y=grp['eff_pct'],
            mode='lines+markers', name=f'{vin:g} V',
        ))
    fig.update_layout(
        title='Buck Efficiency vs. Load Current (per input voltage)',
        xaxis_title='Output load current (mA)',
        yaxis_title='Efficiency (%)',
        legend_title='Vin',
        template='plotly',
        hovermode='x unified',
    )
    fig.update_xaxes(type='log')
    return fig


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Plot buck characterization CSV with Plotly.')
    parser.add_argument('input',
                        help='Input CSV')
    parser.add_argument('--iq-out',
                        help='Iq plot PNG output '
                             '(default: <input basename>_iq.png)')
    parser.add_argument('--eff-out',
                        help='Efficiency plot PNG output '
                             '(default: <input basename>_efficiency.png)')
    parser.add_argument('--show', action='store_true',
                        help='Open plots in a browser instead of only writing '
                             'HTML files')
    parser.add_argument('--min-load-ma', type=float, default=0.0,
                        help='Drop efficiency points below this load current, '
                             'mA (default: 0, plot all)')
    args = parser.parse_args()

    input_path = Path(args.input)
    iq_out = args.iq_out or input_path.with_name(f'{input_path.stem}_iq.png')
    eff_out = args.eff_out or input_path.with_name(
        f'{input_path.stem}_efficiency.png')

    df = pd.read_csv(input_path)

    if (df['test'] == 'iq').any():
        fig = plot_iq(df)
        fig.write_image(iq_out, width=1000, height=600, scale=2)
        print(f"Wrote {iq_out}")
        if args.show:
            fig.show()
    else:
        print("No Iq data found; skipping Iq plot.")

    if (df['test'] == 'efficiency').any():
        fig = plot_efficiency(df, min_load_ma=args.min_load_ma)
        fig.write_image(eff_out, width=1000, height=600, scale=2)
        print(f"Wrote {eff_out}")
        if args.show:
            fig.show()
    else:
        print("No efficiency data found; skipping efficiency plot.")


if __name__ == '__main__':
    main()
