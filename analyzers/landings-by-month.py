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
from data.cache import get_sonde_summaries_as_dataframe

MAPS = {
    'spokane': {
        'bottomleft': (45, -119),
        'topright': (51, -113),
    },
    'seattle': {
        'bottomleft': (46, -125),
        'topright': (49, -121),
    },
    'kitchener': {
        'bottomleft': (40, -83),
        'topright': (46, -77),
    },
    'hilo': {
        'bottomleft': (18, -162),
        'topright': (23, -152),
    },
}


def draw_map(df, title, config):
    # get local landings
    df = df.loc[df['lat'] >= config['bottomleft'][0]]
    df = df.loc[df['lat'] <= config['topright'][0]]
    df = df.loc[df['lon'] >= config['bottomleft'][1]]
    df = df.loc[df['lon'] <= config['topright'][1]]

    # convert to a geodataframe
    gdf = geopandas.GeoDataFrame(
        df,
        geometry=geopandas.points_from_xy(df.lon, df.lat)
    )

    # reproject from wgs84 to web mercator
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)

    # make a 4x3 matrix of matplotlib axes
    fig, axs = plt.subplots(4, 3, figsize=(30, 40))

    for month in range(12):
        ax = axs[month // 3][month % 3]

        # pull out just landings from the month being plotted
        d = gdf.loc[gdf.month == month+1]

        print(f"{title:10s}: {calendar.month_name[month+1]:9s}: {len(d)} landings")

        # plot each landing and set options
        d.plot(ax=ax)
        ax.axis('off')
        ax.set_title(calendar.month_name[month+1])

        # add a map on top
        cx.add_basemap(
            ax,
            crs=d.crs,
            source=cx.providers.OpenStreetMap.Mapnik)

    fig.subplots_adjust(wspace=0, hspace=0)
    fig.tight_layout()
    fn_base = f'{title}-landings-by-month.'
    fig.savefig(fn_base+"png", bbox_inches='tight', pad_inches=0)
    subprocess.check_call(args=["convert", fn_base+"png", fn_base+"webp"])


def main():
    df = get_sonde_summaries_as_dataframe()

    # get landings -- the latest frame received for each serial number
    df = df.loc[df.groupby('serial')['frame'].idxmax()]

    # annotate with month
    df['datetime'] = pd.to_datetime(df['datetime'])
    df['month'] = df['datetime'].dt.month

    for (title, config) in MAPS.items():
        draw_map(df, title, config)


if __name__ == "__main__":
    main()
