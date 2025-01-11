#!/usr/bin/env python3

import calendar
import contextily as cx
import geopandas
import matplotlib.pyplot as plt
import pandas as pd
import subprocess
import sys

cx.set_cache_dir("/tmp/cached-tiles")

sys.path.insert(0, "..")
from data.cache import get_sonde_summaries_as_dataframe, years_covered

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
}


def get_filtered_data(df, config):
    # get local landings
    df = df.loc[
        (df["lat"] >= config["bottomleft"][0])
        & (df["lat"] <= config["topright"][0])
        & (df["lon"] >= config["bottomleft"][1])
        & (df["lon"] <= config["topright"][1])
    ]
    print("Filtered")

    # convert to a geodataframe
    gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.lon, df.lat))
    print("Geoconverted")

    # reproject from wgs84 to web mercator
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)
    print("Reprojected")

    return gdf


def draw_one_map(gdf, ax, title):
    # plot each landing and set options
    gdf.plot(ax=ax)
    ax.axis("off")
    ax.set_title(title)

    # add a map on top
    cx.add_basemap(ax, crs=gdf.crs, source=cx.providers.OpenStreetMap.Mapnik)


def write_fig(fig, filename_base):
    fig.subplots_adjust(wspace=0, hspace=0)
    fig.tight_layout()
    fig.savefig(filename_base + "png", bbox_inches="tight", pad_inches=0)
    subprocess.check_call(
        args=["convert", filename_base + "png", filename_base + "webp"]
    )


def draw_calendar(df, title, config):
    gdf = get_filtered_data(df, config)

    # make a 4x3 matrix of matplotlib axes
    fig, axs = plt.subplots(4, 3, figsize=(30, 40))

    for month in range(12):
        ax = axs[month // 3][month % 3]

        # pull out just landings from the month being plotted
        d = gdf.loc[gdf.month == month + 1]

        print(f"{title:10s}: {calendar.month_name[month + 1]:9s}: {len(d)} landings")
        draw_one_map(d, ax, calendar.month_name[month + 1])

    write_fig(fig, f"{title}-landings-by-month.")


# 1-indexed month
def draw_year_comparison(df, title, config, month):
    gdf = get_filtered_data(df, config)
    years = years_covered(gdf)

    # make a vertical strip of plots
    fig, axs = plt.subplots(len(years), 1, figsize=(10, len(years) * 10))
    for i, year in enumerate(years):
        ax = axs[i]

        # pull out just landings from the year being plotted
        d = gdf.loc[(gdf["datetime"].dt.year == year) & (gdf["month"] == month)]

        print(f"{title:10s}: {year}: {len(d)} landings")
        draw_one_map(d, ax, f"{calendar.month_name[month]} {year}")

    write_fig(fig, f"{title}-landings-by-year.")


def main():
    df = get_sonde_summaries_as_dataframe()
    print("Got data")

    # get landings -- the latest frame received for each serial number
    df = df.loc[df.groupby("serial")["frame"].idxmax()]

    # annotate with month
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["month"] = df["datetime"].dt.month

    for title, config in MAPS.items():
        draw_calendar(df, title, config)
        draw_year_comparison(df, title, config, month=12)


if __name__ == "__main__":
    main()
