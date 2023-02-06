#!/usr/bin/env python3

import calendar
import contextily as cx
import geopandas
import matplotlib.pyplot as plt
import pandas as pd

cx.set_cache_dir("/tmp/cached-tiles")

LAT_MIN = 46
LAT_MAX = 49
LON_MIN = -125
LON_MAX = -121

def main():
    df = pd.read_parquet('sonde-summaries-2022.parquet')

    # get landings
    df = df.loc[(df.vel_v < 0) & (df.alt < 10000)]

    # get local landings
    df = df.loc[(df.lat >= LAT_MIN) & (df.lat <= LAT_MAX)]
    df = df.loc[(df.lon >= LON_MIN) & (df.lon <= LON_MAX)]

    # annotate with month
    df['datetime'] = pd.to_datetime(df['datetime'])
    df['month'] = df['datetime'].dt.month

    # convert to a geodataframe
    gdf = geopandas.GeoDataFrame(
        df,
        geometry=geopandas.points_from_xy(df.lon, df.lat)
    )

    # reproject from wgs84 to web mercator
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)

    fig, axs = plt.subplots(4, 3, figsize=(30, 40))

    for month in range(12):
        ax = axs[month//3][month%3]

        d = gdf.loc[gdf.month == month+1]
        d.plot(ax=ax)
        ax.axis('off')
        ax.set_title(calendar.month_name[month+1])
        cx.add_basemap(
            ax,
            crs=d.crs,
            source=cx.providers.OpenStreetMap.Mapnik)

    fig.subplots_adjust(wspace=0, hspace=0)
    fig.tight_layout()
    fig.savefig('seattle-landings-by-month.png', bbox_inches='tight', pad_inches=0)

if __name__ == "__main__":
    main()
