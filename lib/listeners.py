"""
Listener analysis for radiosondes.

Analyzes which feeder stations (listeners) were able to hear a particular sonde,
providing coverage statistics and frame-by-frame breakdown.
"""

import pandas as pd
import requests
import sondehub


def get_listener_stats(sondeid):
    """
    Analyze listener coverage for a given sonde.

    Args:
        sondeid: The serial number of the sonde to analyze

    Returns:
        A dictionary with two keys:
        - 'stats': DataFrame with per-listener statistics (frame range, coverage %, etc.)
        - 'coverage': Series showing how many listeners heard each combination of frames
        - 'warning': Optional warning message if using live API

    Raises:
        ValueError: If the sonde cannot be found
    """
    df = pd.DataFrame(sondehub.download(serial=sondeid))
    warning = None

    if len(df) == 0:
        df = pd.DataFrame(
            requests.get(f"https://api.v2.sondehub.org/sonde/{sondeid}").json()
        )
        warning = "Using live data API that only returns one listener per data point"

    if len(df) == 0:
        raise ValueError(f"Cannot find sonde '{sondeid}'")

    # Get only the first instance of each frame returned by each uploader
    df = df.groupby(["uploader_callsign", "frame"]).first().reset_index()

    df["date"] = pd.to_datetime(df["datetime"]).dt.round("s")  # type: ignore[call-overload]
    df["time"] = df["date"].dt.strftime("%H:%M:%SZ")
    df["alt"] = df["alt"].astype(int)
    df["vel_v"] = df["vel_v"].astype(float).round(1)

    # Aggregate stats per listener
    agg = df.groupby("uploader_callsign").agg(
        {
            "frame": ["first", "last", "count"],
            "time": ["first", "last"],
            "alt": ["first", "last"],
            "vel_v": ["first", "last"],
        }
    )

    # Calculate coverage percentage
    agg.insert(  # type: ignore[call-overload]
        3,
        "cov%",
        agg[("frame", "count")]
        / (1 + agg[("frame", "last")] - agg[("frame", "first")]),
    )
    agg["cov%"] = (agg["cov%"] * 100).round(1)  # type: ignore[index]
    agg = agg.sort_values([("frame", "last")], ascending=False)  # type: ignore[call-overload]

    # Calculate how many points were heard by which combinations of listeners
    who_per_point = df.groupby("frame")["uploader_callsign"].agg(
        lambda x: ",".join(sorted(set(x)))
    )
    coverage_counts = who_per_point.value_counts()

    return {
        'stats': agg,
        'coverage': coverage_counts,
        'warning': warning
    }
