#!/usr/bin/env python3

import argparse
import os
import sys
from typing import Tuple

import contextily as cx
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
from pyproj import Transformer
import requests
import sondehub

matplotlib.use('Agg')
cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))


def to_mercator_xy(lat, lon):
    """Convert WGS84 lat/lon to Web Mercator x/y coordinates."""
    wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
    return wgs84_to_mercator.transform(lat, lon)


MAP_WHITESPACE = 0.2


def get_ground_elevation(lat, lon):
    """Get ground elevation at a given lat/lon using USGS elevation API.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        Ground elevation in meters, or None if the API call fails
    """
    try:
        resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
            'x': lon,
            'y': lat,
            'units': 'Meters',
            'wkid': '4326',
            'includeDate': 'True',
        })
        resp.raise_for_status()
        return float(resp.json()['value'])
    except Exception as e:
        print(f'Elevation API gave invalid response: {e}')
        return None


def get_map_limits(points) -> Tuple[float, float, float, float, float]:
    """Calculate map boundaries and zoom level for given points.

    Args:
        points: List of (lat, lon) tuples

    Returns:
        min_x, min_y, max_x, max_y, zoom
    """
    min_lat = min([point[0] for point in points])
    max_lat = max([point[0] for point in points])
    min_lon = min([point[1] for point in points])
    max_lon = max([point[1] for point in points])
    min_x, min_y = to_mercator_xy(min_lat, min_lon)
    max_x, max_y = to_mercator_xy(max_lat, max_lon)
    x_pad = (max_x - min_x) * MAP_WHITESPACE
    y_pad = (max_y - min_y) * MAP_WHITESPACE
    max_pad = max(x_pad, y_pad)
    min_x -= max_pad
    max_x += max_pad
    min_y -= max_pad
    max_y += max_pad

    # Calculate the zoom
    lat_length = max_lat - min_lat
    lon_length = max_lon - min_lon
    zoom_lat = np.ceil(np.log2(360 * 2.0 / lat_length))
    zoom_lon = np.ceil(np.log2(360 * 2.0 / lon_length))
    zoom = np.min([zoom_lon, zoom_lat])
    zoom = int(zoom) + 1
    zoom = min(zoom, 18)  # limit to max zoom level of tiles

    return min_x, min_y, max_x, max_y, zoom


def draw_ground_points_map(ground_points, size=10):
    """Draw a map containing all ground points.

    Args:
        ground_points: DataFrame with 'lat' and 'lon' columns
        size: Figure size in inches

    Returns:
        matplotlib figure object
    """
    fig, ax = plt.subplots(figsize=(size, size))
    ax.set_aspect('equal')

    # Convert all ground points to mercator coordinates
    ground_x, ground_y = to_mercator_xy(ground_points['lat'].values, ground_points['lon'].values)

    # Plot all ground points
    ax.scatter(ground_x, ground_y, color='red', s=50, alpha=0.6, marker='o', label='Ground points')

    # Calculate weighted average of lat/lon (equal weights for now)
    avg_lat = ground_points['lat'].mean()
    avg_lon = ground_points['lon'].mean()
    avg_x, avg_y = to_mercator_xy(avg_lat, avg_lon)

    # Plot the weighted average point
    ax.scatter(avg_x, avg_y, color='blue', s=200, alpha=0.8, marker='*',
               label='Weighted average', edgecolors='black', linewidths=2, zorder=5)

    # Calculate standard deviation in meters
    # Since we're in mercator (meters), we can calculate std dev directly from distances
    mercator_points_x = ground_x - avg_x  # distances from average in meters
    mercator_points_y = ground_y - avg_y
    std_dev_x = np.std(mercator_points_x)
    std_dev_y = np.std(mercator_points_y)
    std_dev_combined = np.sqrt(std_dev_x**2 + std_dev_y**2)

    # Calculate altitude statistics
    avg_alt = ground_points['alt'].mean()
    std_dev_alt = ground_points['alt'].std()

    # Get ground elevation at the weighted average position
    ground_elev = get_ground_elevation(avg_lat, avg_lon)

    # Print the weighted average and std dev
    print(f"Weighted average position: {avg_lat:.6f}, {avg_lon:.6f}")
    print(f"Standard deviation: E-W: {std_dev_x:.1f}m, N-S: {std_dev_y:.1f}m, Combined: {std_dev_combined:.1f}m")
    altitude_line = f"Altitude: {avg_alt:.1f}m (±{std_dev_alt:.1f}m)"
    if ground_elev is not None:
        height_agl = avg_alt - ground_elev
        altitude_line += f", Ground: {ground_elev:.1f}m, AGL: {height_agl:.1f}m"
    print(altitude_line)

    # Prepare list of points for map limits calculation
    map_limits = [[lat, lon] for lat, lon in zip(ground_points['lat'], ground_points['lon'])]

    # Find the limits of the map
    min_x, min_y, max_x, max_y, zoom = get_map_limits(map_limits)
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    print(f"Downloading basemap at zoom level {zoom}")

    cx.add_basemap(
        ax,
        zoom=zoom,
        crs='EPSG:3857',
        source=cx.providers.OpenStreetMap.Mapnik,
    )

    # Set up axes with tick marks in meters
    # Use the weighted average as the origin point for relative distances
    def mercator_to_meters_x(x):
        """Convert mercator x coordinate to meters from average point."""
        return x - avg_x

    def mercator_to_meters_y(y):
        """Convert mercator y coordinate to meters from average point."""
        return y - avg_y

    # Create secondary axes showing distances in meters
    ax.set_xlabel('East-West distance from average (m)', fontsize=10)
    ax.set_ylabel('North-South distance from average (m)', fontsize=10)

    # Format the tick labels to show meters
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{int(mercator_to_meters_x(x))}'))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, p: f'{int(mercator_to_meters_y(y))}'))

    # Add grid for easier reading
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

    # Add text box at the top with statistics
    stats_text = f"Weighted Average: {avg_lat:.6f}, {avg_lon:.6f}\n"
    stats_text += f"Std Dev: E-W {std_dev_x:.1f}m, N-S {std_dev_y:.1f}m, Combined {std_dev_combined:.1f}m\n"
    stats_text += f"Altitude: {avg_alt:.1f}m (\u00b1{std_dev_alt:.1f}m)"
    if ground_elev is not None:
        height_agl = avg_alt - ground_elev
        stats_text += f", Ground: {ground_elev:.1f}m, AGL: {height_agl:.1f}m"
    ax.text(0.5, 0.98, stats_text,
            transform=ax.transAxes,
            fontsize=9,
            verticalalignment='top',
            horizontalalignment='center',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8))

    # Add legend
    ax.legend(loc='lower left', framealpha=0.9)

    fig.tight_layout()

    return fig


def get_listeners(sondeid):
    df = pd.DataFrame(sondehub.download(serial=sondeid))
    if len(df) == 0:
        sys.exit(f"Can not find sonde '{sondeid}'")

    # Find first spot where we can consider it on the ground -- vertical and horizontal speed both <1 m/s
    landing = df.loc[(df['vel_v'].abs() < 1) & (df['vel_h'].abs() < 1)]
    if len(landing) == 0:
        sys.exit(f"Sonde '{sondeid}' does not appear to have ground reception")

    # Get all points received after landing
    landing_frame = landing['frame'].min()
    ground_points = df.loc[df['frame'] >= landing_frame]
    print(f"Found {len(ground_points)} ground points for sonde '{sondeid}'")

    # Draw a map of all ground points
    fig = draw_ground_points_map(ground_points)
    output_filename = f"ground_points_{sondeid}.png"
    fig.savefig(output_filename, bbox_inches='tight', dpi=150)
    plt.close('all')
    print(f"Map saved to {output_filename}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sondeid",
        nargs=1,
    )
    args = parser.parse_args(sys.argv[1:])
    get_listeners(args.sondeid[0])
