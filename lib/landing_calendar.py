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
from PIL import Image
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.map_utils import setup_contextily_cache
from data.cache import get_sonde_summaries_as_dataframe
from lib.data_utils import filter_real_flights, get_landing_rows

matplotlib.use('Agg')

# Disable contextily's in-memory tile caching to prevent memory growth
setup_contextily_cache()

# Calendar grid layout
CALENDAR_COLS = 3
CALENDAR_ROWS = 4


_LANDING_DATA_COLUMNS = ['serial', 'frame', 'lat', 'lon', 'alt', 'datetime']


def _get_landing_data():
    """Load and prepare sonde landing data.

    Only reads the columns needed for calendar generation, filters to real
    flights, and reduces to landing rows (last frame per sonde) to minimize
    memory usage.
    """
    df = get_sonde_summaries_as_dataframe(columns=_LANDING_DATA_COLUMNS)

    # Filter out ground tests and non-flights
    df = filter_real_flights(df)

    # Get landings -- the latest frame received for each serial number
    df = get_landing_rows(df)

    # Annotate with datetime and month
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["month"] = df["datetime"].dt.month

    return df


# Size of each individual month subplot in inches
MONTH_FIGSIZE = (10, 10)


# Generate calendar for given bounds
def generate_calendar(bottom_lat, left_lon, top_lat, right_lon, format='png'):
    """Generate a 12-month calendar of sonde landings within the given bounds.

    Renders each month as an individual matplotlib figure to keep peak memory
    low, then composites the 12 images into a grid using PIL.

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

    try:
        # Load and prepare landing data
        df = _get_landing_data()

        # Filter to landings within bounds and free the full dataset
        gdf = _filter_and_project(df, bottom_lat, left_lon, top_lat, right_lon)
        df = None

        # Annotate with month if not already present
        if 'month' not in gdf.columns:
            gdf['month'] = gdf['datetime'].dt.month

        # Render each month individually and collect as PIL images
        month_images = []
        for month in range(12):
            month_data = gdf.loc[gdf.month == month + 1]
            img = _render_one_month(month_data, calendar.month_name[month + 1], gdf.crs)
            month_images.append(img)

        # Free the dataframes before compositing
        df = None
        gdf = None
        gc.collect()

        # Composite into a grid
        return _composite_grid(month_images, format)

    finally:
        df = None
        gdf = None
        gc.collect()


def _render_one_month(gdf, title, crs):
    """Render a single month's map and return it as a PIL Image.

    Creates a temporary matplotlib figure, renders the map, converts to a PIL
    image, then closes the figure to release memory before returning.
    """
    fig = None
    buf = None
    try:
        fig, ax = plt.subplots(1, 1, figsize=MONTH_FIGSIZE)
        _draw_one_map(gdf, ax, title, crs)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', pad_inches=0)
        buf.seek(0)
        img = Image.open(buf).copy()  # .copy() so we own the pixels
        return img
    finally:
        if fig is not None:
            plt.close(fig)
        if buf is not None:
            buf.close()
        gc.collect()


def _composite_grid(images, format):
    """Arrange a list of PIL Images into a CALENDAR_ROWS x CALENDAR_COLS grid.

    Returns the composited image as bytes in the requested format.
    """
    cell_w = max(img.width for img in images)
    cell_h = max(img.height for img in images)

    grid = Image.new('RGB', (cell_w * CALENDAR_COLS, cell_h * CALENDAR_ROWS), 'white')

    for i, img in enumerate(images):
        col = i % CALENDAR_COLS
        row = i // CALENDAR_COLS
        # Center the image within its cell
        x = col * cell_w + (cell_w - img.width) // 2
        y = row * cell_h + (cell_h - img.height) // 2
        grid.paste(img, (x, y))
        img.close()

    buf = io.BytesIO()
    grid.save(buf, format=format.upper())
    buf.seek(0)
    result = buf.read()
    grid.close()
    buf.close()
    return result


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

        # Find python executable - sys.executable may be uwsgi in production,
        # but it's in the same conda env so python is in the same directory
        python_exe = os.path.join(os.path.dirname(sys.executable), 'python')

        result = subprocess.run(
            [
                python_exe,
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
