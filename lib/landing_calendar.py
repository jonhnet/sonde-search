"""
Shared library for generating landing calendars showing sonde landing locations by month.
"""

import calendar
import contextily as cx
import geopandas
import io
import matplotlib
import matplotlib.pyplot as plt
import os
import pandas as pd
import sys

matplotlib.use('Agg')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from data.cache import get_sonde_summaries_as_dataframe


def _get_landing_data():
    """Load and prepare sonde landing data."""
    df = get_sonde_summaries_as_dataframe()

    # Get landings -- the latest frame received for each serial number
    df = df.loc[df.groupby("serial")["frame"].idxmax()]

    # Annotate with datetime and month
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["month"] = df["datetime"].dt.month

    return df


# Generate calendar for given bounds
def generate_calendar(bottom_lat, left_lon, top_lat, right_lon, format='png'):
    """Generate a 12-month calendar of sonde landings within the given bounds.

    Args:
        bottom_lat: Southern boundary
        left_lon: Western boundary
        top_lat: Northern boundary
        right_lon: Eastern boundary
        format: Output format ('png' or 'webp')

    Returns:
        Bytes of the generated image
    """
    # Load and prepare landing data
    df = _get_landing_data()

    # Filter to landings within bounds
    gdf = _filter_and_project(df, bottom_lat, left_lon, top_lat, right_lon)

    # Annotate with month if not already present
    if 'month' not in gdf.columns:
        gdf['month'] = gdf['datetime'].dt.month

    # Create 4x3 grid of subplots (12 months)
    fig, axs = plt.subplots(4, 3, figsize=(30, 40))

    for month in range(12):
        ax = axs[month // 3][month % 3]

        # Filter to just this month
        month_data = gdf.loc[gdf.month == month + 1]

        # Draw the map for this month
        _draw_one_map(month_data, ax, calendar.month_name[month + 1], gdf.crs)

    # Save to bytes
    fig.subplots_adjust(wspace=0, hspace=0)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format=format, bbox_inches='tight', pad_inches=0)
    plt.close(fig)

    buf.seek(0)
    return buf.read()


def _filter_and_project(df, bottom_lat, left_lon, top_lat, right_lon):
    """Filter dataframe to bounds and convert to geopandas with Web Mercator projection."""
    # Filter to geographic bounds
    filtered = df.loc[
        (df['lat'] >= bottom_lat)
        & (df['lat'] <= top_lat)
        & (df['lon'] >= left_lon)
        & (df['lon'] <= right_lon)
    ]

    # Convert to geodataframe
    gdf = geopandas.GeoDataFrame(
        filtered,
        geometry=geopandas.points_from_xy(filtered.lon, filtered.lat)
    )

    # Reproject from WGS84 to Web Mercator
    gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=3857)

    return gdf


def _draw_one_map(gdf, ax, title, crs):
    """Draw a single month's map on the given axes."""
    # Plot landing points
    gdf.plot(ax=ax)
    ax.axis('off')
    ax.set_title(title)

    # Add basemap
    cx.add_basemap(ax, crs=crs, source=cx.providers.OpenStreetMap.Mapnik)
