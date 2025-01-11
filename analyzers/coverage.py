#!/usr/bin/env python3

DEFAULT_LISTENER_LATLON = "47.61262,-122.32944"
DEFAULT_LISTENER_ALT = "100"

from pyproj import Transformer
import argparse
import contextily as cx
import glob
import matplotlib
import matplotlib.pyplot as plt
import os
import pandas as pd
import sys
import AltAzRange

matplotlib.use("Agg")

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

wgs84_to_mercator = Transformer.from_crs(crs_from="EPSG:4326", crs_to="EPSG:3857")


def to_mercator_xy(lat, lon):
    return wgs84_to_mercator.transform(lat, lon)


def plot(logfile_dir, listener_lat, listener_lon, listener_alt):
    # Read all log files and concatenate them together
    dfs = []
    for fn in glob.glob(os.path.join(logfile_dir, "*.log")):
        dfs.append(pd.read_csv(fn))
    df = pd.concat(dfs)

    # Annotate each point with azimuth, elevation and range from the observing
    # station
    el = AltAzRange.AltAzimuthRange()
    el.observer(listener_lat, listener_lon, listener_alt)

    def compute_el(row):
        el.target(row.lat, row.lon, row.alt)
        return el.calculate()

    df = pd.concat([df, df.apply(compute_el, axis=1, result_type="expand")], axis=1)

    # Make an elevation vs azimuth plot
    fig, ax = plt.subplots(figsize=(10, 10))
    df.plot.scatter(ax=ax, x="azimuth", y="elevation", grid=True)
    fig.tight_layout()
    fig.savefig("az-vs-el.png", bbox_inches="tight")

    # Plot all coverage on a map
    (home_x, home_y) = to_mercator_xy(listener_lat, listener_lon)

    fig, ax = plt.subplots(figsize=(25, 25))
    ax.axis("off")
    heard_points = to_mercator_xy(df.lat, df.lon)
    heard_points = zip(heard_points[0], heard_points[1])
    for point in heard_points:
        ax.plot([home_x, point[0]], [home_y, point[1]], color="red", alpha=0.01)
    cx.add_basemap(
        ax,
        source=cx.providers.OpenStreetMap.Mapnik,
    )
    fig.tight_layout()
    fig.savefig("coverage-map.png", bbox_inches="tight")

    # Make a tigheter map
    ax.set_xlim([home_x - 1609 * 1, home_x + 1609 * 0.05])
    ax.set_ylim([home_y - 1609 * 0.5, home_y + 1609 * 0.75])
    cx.add_basemap(
        ax,
        zoom=17,
        source=cx.providers.OpenStreetMap.Mapnik,
    )
    fig.savefig("coverage-map-tight.png", bbox_inches="tight")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d",
        "--logfile-dir",
        default=".",
        action="store",
        required=True,
    )
    parser.add_argument(
        "-l",
        "--listener-latlon",
        default=DEFAULT_LISTENER_LATLON,
        action="store",
    )
    parser.add_argument(
        "-a",
        "--listener-alt",
        default=DEFAULT_LISTENER_ALT,
        action="store",
    )
    args = parser.parse_args(sys.argv[1:])
    (lat, lon) = args.listener_latlon.split(",")
    lat = float(lat)
    lon = float(lon)
    alt = float(args.listener_alt)
    plot(args.logfile_dir, lat, lon, alt)
