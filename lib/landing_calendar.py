"""
Shared library for generating landing calendars showing sonde landing locations by month.

Can be run as a CLI tool:
    python landing_calendar.py --bottom-lat 39 --left-lon -76 --top-lat 41 --right-lon -74 --output /tmp/calendar.webp

Or imported and called via generate_calendar_subprocess() which spawns a subprocess
to avoid memory accumulation in long-running processes.
"""

import argparse
import calendar
import contextily as cx
import gc
import geopandas
import io
import matplotlib
import matplotlib.pyplot as plt
import os
import pandas as pd
import subprocess
import sys
import tempfile

matplotlib.use('Agg')

# Disable contextily's in-memory tile caching to prevent memory growth
cx.set_cache_dir(os.path.join(os.path.expanduser("~"), ".cache/geotiles"))

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
    df = None
    gdf = None
    fig = None
    buf = None

    try:
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
        buf.seek(0)
        result = buf.read()
        return result

    finally:
        # Explicitly close and cleanup matplotlib to prevent memory leaks
        if fig is not None:
            plt.close(fig)
        plt.close('all')

        # Close the BytesIO buffer
        if buf is not None:
            buf.close()

        # Delete references and force garbage collection
        del df, gdf, fig, buf
        gc.collect()


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


def generate_calendar_to_file(bottom_lat, left_lon, top_lat, right_lon, output_path, format='webp'):
    """Generate calendar and write directly to a file.

    Args:
        bottom_lat: Southern boundary
        left_lon: Western boundary
        top_lat: Northern boundary
        right_lon: Eastern boundary
        output_path: Path to write the output image
        format: Output format ('png' or 'webp')
    """
    image_bytes = generate_calendar(bottom_lat, left_lon, top_lat, right_lon, format=format)
    with open(output_path, 'wb') as f:
        f.write(image_bytes)


def generate_calendar_subprocess(bottom_lat, left_lon, top_lat, right_lon, format='webp'):
    """Generate calendar in a subprocess to avoid memory accumulation.

    This spawns a separate Python process that loads the data, generates the
    calendar, writes it to a temp file, and exits. This ensures all memory
    is released when the subprocess terminates.

    Args:
        bottom_lat: Southern boundary
        left_lon: Western boundary
        top_lat: Northern boundary
        right_lon: Eastern boundary
        format: Output format ('png' or 'webp')

    Returns:
        Bytes of the generated image
    """
    # Create a temp file for the output
    with tempfile.NamedTemporaryFile(suffix=f'.{format}', delete=False) as f:
        output_path = f.name

    try:
        # Run this module as a script in a subprocess
        script_path = os.path.abspath(__file__)
        result = subprocess.run(
            [
                sys.executable,
                script_path,
                '--bottom-lat', str(bottom_lat),
                '--left-lon', str(left_lon),
                '--top-lat', str(top_lat),
                '--right-lon', str(right_lon),
                '--output', output_path,
                '--format', format,
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(script_path)),  # Run from repo root
        )

        if result.returncode != 0:
            raise RuntimeError(f"Calendar generation failed: {result.stderr}")

        # Read the result
        with open(output_path, 'rb') as f:
            return f.read()

    finally:
        # Clean up temp file
        if os.path.exists(output_path):
            os.unlink(output_path)


def main():
    """CLI entry point for generating calendars."""
    parser = argparse.ArgumentParser(description='Generate sonde landing calendar')
    parser.add_argument('--bottom-lat', type=float, required=True, help='Southern boundary latitude')
    parser.add_argument('--left-lon', type=float, required=True, help='Western boundary longitude')
    parser.add_argument('--top-lat', type=float, required=True, help='Northern boundary latitude')
    parser.add_argument('--right-lon', type=float, required=True, help='Eastern boundary longitude')
    parser.add_argument('--output', type=str, required=True, help='Output file path')
    parser.add_argument('--format', type=str, default='webp', choices=['png', 'webp'], help='Output format')

    args = parser.parse_args()

    generate_calendar_to_file(
        args.bottom_lat,
        args.left_lon,
        args.top_lat,
        args.right_lon,
        args.output,
        format=args.format,
    )


if __name__ == '__main__':
    main()
