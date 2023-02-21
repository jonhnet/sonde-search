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
import pandas as pd
import sondehub
import sys
import requests

def get_listeners(sondeid):
    #df = pd.DataFrame(sondehub.download(serial=sondeid))
    df = pd.DataFrame(requests.get(f'https://api.v2.sondehub.org/sonde/{sondeid}').json())
    if len(df) == 0:
        sys.exit(f"Can not find sonde '{sondeid}'")
    df['date'] = pd.to_datetime(df['datetime']).round('s')
    df['time'] = df['date'].dt.strftime("%H:%M:%SZ")
    df['alt'] = df['alt'].astype(int)
    df['vel_v'] = df['vel_v'].round(1)
    df = df.sort_values('frame')
    agg = df.groupby('uploader_callsign').agg({
        'frame': ['first', 'last'],
        'time': ['first', 'last'],
        'alt': ['first', 'last'],
        'vel_v': ['first', 'last'],
    })
    print(agg.to_string())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'sondeid',
        nargs=1,
    )
    args = parser.parse_args(sys.argv[1:])
    get_listeners(args.sondeid[0])
