#!/usr/bin/env python3

# Given a sonde id, this prints a summary of which feeder stations were able to
# hear it. It prints a table like this:
#
# $ ./listeners.py U3450381
#                   frame             time               alt        vel_v
#                   first  last      first       last  first   last first  last
# uploader_callsign
# KB1LQD             2905  7491  11:28:09Z  12:44:35Z   7990  21237   5.4 -19.3
# KK6HMI-2           2836  7917  11:27:00Z  12:51:41Z   7567  12486   5.9 -19.5
# WA7336SWL          3702  8192  11:41:26Z  12:56:16Z  12804   8335   3.3 -14.8
#

import argparse
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib import listeners


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sondeid",
        nargs=1,
    )
    args = parser.parse_args(sys.argv[1:])
    sondeid = args.sondeid[0]

    try:
        result = listeners.get_listener_stats(sondeid)

        if result['warning']:
            print(f"Warning: {result['warning']}")

        print(result['stats'].to_string())

        print("\nNumber of points heard by:")
        print(result['coverage'].to_string())

    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
