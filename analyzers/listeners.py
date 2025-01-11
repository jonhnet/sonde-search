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
    df = pd.DataFrame(sondehub.download(serial=sondeid))
    live = False
    if len(df) == 0:
        df = pd.DataFrame(
            requests.get(f"https://api.v2.sondehub.org/sonde/{sondeid}").json()
        )
        live = True
    if len(df) == 0:
        sys.exit(f"Can not find sonde '{sondeid}'")
    if live:
        print("Warning: using data api that only returns one listener per data point")

    # Get only the first instance of each frame returned by each uploader
    df = df.groupby(["uploader_callsign", "frame"]).first().reset_index()

    df["date"] = pd.to_datetime(df["datetime"]).round("s")
    df["time"] = df["date"].dt.strftime("%H:%M:%SZ")
    df["alt"] = df["alt"].astype(int)
    df["vel_v"] = df["vel_v"].astype(float).round(1)
    agg = df.groupby("uploader_callsign").agg(
        {
            "frame": ["first", "last", "count"],
            "time": ["first", "last"],
            "alt": ["first", "last"],
            "vel_v": ["first", "last"],
        }
    )
    agg.insert(
        3,
        "cov%",
        agg[("frame", "count")]
        / (1 + agg[("frame", "last")] - agg[("frame", "first")]),
    )
    agg["cov%"] = (agg["cov%"] * 100).round(1)
    agg = agg.sort_values([("frame", "last")], ascending=False)
    print(agg.to_string())

    print("\nNumber of points heard by:")
    who_per_point = df.groupby("frame")["uploader_callsign"].agg(
        lambda x: ",".join(sorted(set(x)))
    )
    print(who_per_point.value_counts().to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sondeid",
        nargs=1,
    )
    args = parser.parse_args(sys.argv[1:])
    get_listeners(args.sondeid[0])
