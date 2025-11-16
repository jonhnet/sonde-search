#!/usr/bin/env python3

# Given a sonde serial number, generate a KML file for viewing in Google Earth.
#
# Usage:
#   ./kml_generator.py V1854526

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib import kml_generator


def main():
    parser = argparse.ArgumentParser(
        description='Generate KML file for a radiosonde flight path'
    )
    parser.add_argument(
        "serial",
        help="Sonde serial number (e.g., V1854526)"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (default: SERIAL.kml)",
        type=str
    )
    args = parser.parse_args()

    # Determine output filename
    output_file = args.output if args.output else f"{args.serial}.kml"

    try:
        kml_content = kml_generator.generate_kml(args.serial)
        with open(output_file, 'w') as f:
            f.write(kml_content)
        print(f"KML file generated: {output_file}")
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
