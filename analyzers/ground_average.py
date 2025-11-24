#!/usr/bin/env python3

import argparse
import os
import sys

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import sondehub

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import lib.map_utils as map_utils

matplotlib.use('Agg')


def get_listeners(sondeid):
    df = pd.DataFrame(sondehub.download(serial=sondeid))
    if len(df) == 0:
        sys.exit(f"Can not find sonde '{sondeid}'")

    # Identify ground points using the common library
    ground_points = map_utils.identify_ground_points(df)
    if ground_points is None:
        sys.exit(f"Sonde '{sondeid}' does not appear to have ground reception")

    print(f"Found {len(ground_points)} ground points for sonde '{sondeid}'")

    # Draw a map of all ground points using the common library
    mu = map_utils.MapUtils()
    fig, stats = map_utils.draw_ground_reception_map(ground_points, mu)
    output_filename = f"ground_points_{sondeid}.png"
    fig.savefig(output_filename, bbox_inches='tight', dpi=150)
    plt.close('all')
    print(f"Map saved to {output_filename}")
    print(f"Average position: {stats.avg_lat:.6f}, {stats.avg_lon:.6f}")
    print(f"Position error: ±{stats.std_dev_combined:.1f}m")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sondeid",
        nargs=1,
    )
    args = parser.parse_args(sys.argv[1:])
    get_listeners(args.sondeid[0])
