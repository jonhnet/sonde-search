#!/usr/bin/env python3

import argparse
import contextily as cx
import os
import subprocess
import sys

cx.set_cache_dir("/tmp/cached-tiles")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.landing_calendar import generate_calendar

MAPS = {
    "spokane": {
        "bottomleft": (45, -119),
        "topright": (51, -113),
    },
    "seattle": {
        "bottomleft": (46, -125),
        "topright": (49, -121),
    },
    "kitchener": {
        "bottomleft": (40, -83),
        "topright": (46, -77),
    },
    "hilo": {
        "bottomleft": (18, -162),
        "topright": (23, -152),
    },
    "madison": {
        "bottomleft": (40, -93),
        "topright": (46, -86),
    },
}


def draw_calendar(title, config):
    """Generate calendar for a named region."""
    bottom_lat = config["bottomleft"][0]
    left_lon = config["bottomleft"][1]
    top_lat = config["topright"][0]
    right_lon = config["topright"][1]

    # Generate PNG
    png_bytes = generate_calendar(bottom_lat, left_lon, top_lat, right_lon, format='png')
    png_filename = f"{title}-landings-by-month.png"
    with open(png_filename, 'wb') as f:
        f.write(png_bytes)
    print(f"Generated {png_filename}")

    # Convert to WebP
    webp_filename = f"{title}-landings-by-month.webp"
    subprocess.check_call(args=["convert", png_filename, webp_filename])
    print(f"Generated {webp_filename}")


def main():
    parser = argparse.ArgumentParser(description='Generate landing calendars for predefined regions or custom bounds')
    parser.add_argument('--region', choices=list(MAPS.keys()), help='Predefined region name')
    parser.add_argument('--bounds', nargs=4, type=float, metavar=('BOTTOM_LAT', 'LEFT_LON', 'TOP_LAT', 'RIGHT_LON'),
                        help='Custom bounds: bottom_lat left_lon top_lat right_lon')
    parser.add_argument('--output', default='calendar', help='Output filename base (default: calendar)')

    args = parser.parse_args()

    # Generate calendar(s)
    if args.region:
        # Use predefined region
        draw_calendar(args.region, MAPS[args.region])
    elif args.bounds:
        # Use custom bounds
        config = {
            "bottomleft": (args.bounds[0], args.bounds[1]),
            "topright": (args.bounds[2], args.bounds[3]),
        }
        draw_calendar(args.output, config)
    else:
        # Generate all predefined regions
        for title, config in MAPS.items():
            draw_calendar(title, config)


if __name__ == "__main__":
    main()
