"""
Shared utilities for generating maps of sonde flights and landing locations.
"""

from dataclasses import dataclass
from typing import Tuple, Optional
import contextily as cx
import matplotlib.figure
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np
import pandas as pd
import requests
from pyproj import Transformer


# Whitespace padding around map boundaries (20%)
MAP_WHITESPACE = 0.2


@dataclass
class GroundReceptionStats:
    """Statistics about ground reception points."""
    avg_lat: float
    avg_lon: float
    num_points: int
    std_dev_lat: float  # Standard deviation in degrees
    std_dev_lon: float  # Standard deviation in degrees
    std_dev_x: float  # Standard deviation in meters (East-West)
    std_dev_y: float  # Standard deviation in meters (North-South)
    std_dev_combined: float  # Combined standard deviation in meters
    avg_alt: float
    std_dev_alt: float
    ground_elev: Optional[float] = None


class MapUtils:
    """Utilities for coordinate transformation and map boundary calculation."""

    def __init__(self):
        # Create transformer once per instance
        self.wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')

    # Convert WGS84 lat/lon to Web Mercator x/y coordinates
    def to_mercator_xy(self, lat, lon):
        return self.wgs84_to_mercator.transform(lat, lon)

    # Calculate map boundaries and zoom level for given points
    def get_map_limits(self, points) -> Tuple[float, float, float, float, float]:
        min_lat = min([point[0] for point in points])
        max_lat = max([point[0] for point in points])
        min_lon = min([point[1] for point in points])
        max_lon = max([point[1] for point in points])
        min_x, min_y = self.to_mercator_xy(min_lat, min_lon)
        max_x, max_y = self.to_mercator_xy(max_lat, max_lon)
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


# Get ground elevation at a given lat/lon.
# First tries USGS (US only, ~10m resolution), then falls back to
# OpenTopoData (global coverage, 10-30m resolution depending on region).
def get_elevation(lat, lon):
    # Try USGS first (US only, ~10m resolution)
    try:
        resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
            'x': lon,
            'y': lat,
            'units': 'Meters',
            'wkid': '4326',
            'includeDate': 'True',
        }, timeout=10)
        resp.raise_for_status()
        value = resp.json().get('value')
        if value is not None:
            return float(value)
    except Exception:
        pass

    # Fall back to OpenTopoData with multiple datasets:
    # ned10m (10m US), eudem25m (25m Europe), srtm30m (30m global)
    try:
        resp = requests.get(
            'https://api.opentopodata.org/v1/ned10m,eudem25m,srtm30m',
            params={'locations': f'{lat},{lon}'},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get('results', [])
        if results and results[0].get('elevation') is not None:
            return float(results[0]['elevation'])
    except Exception:
        pass

    return None


def identify_ground_points(flight_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Identify ground reception points from a flight DataFrame.

    Ground points are defined as frames where both vertical and horizontal
    velocities are less than 1 m/s.

    Args:
        flight_df: DataFrame with flight telemetry including 'vel_v', 'vel_h',
                   and 'frame' columns

    Returns:
        DataFrame containing only the ground points, or None if no ground
        points found
    """
    # Find first spot where we can consider it on the ground -- vertical and
    # horizontal speed both <1 m/s
    landing = flight_df.loc[(flight_df['vel_v'].abs() < 1) & (flight_df['vel_h'].abs() < 1)]
    if len(landing) == 0:
        return None

    # Get all points received after landing
    landing_frame = landing['frame'].min()
    ground_points = flight_df.loc[flight_df['frame'] >= landing_frame]

    return ground_points


def draw_ground_reception_map(ground_points: pd.DataFrame, map_utils: Optional['MapUtils'] = None,
                               size: int = 10) -> Tuple[matplotlib.figure.Figure, GroundReceptionStats]:
    """Draw a map showing ground reception points with statistics.

    Creates a map with:
    - All ground reception points plotted as red dots
    - Weighted average position as a blue star
    - Statistics including standard deviation and altitude info
    - Axes showing distance from average point in meters

    Args:
        ground_points: DataFrame with 'lat', 'lon', and 'alt' columns
        map_utils: MapUtils instance (creates one if not provided)
        size: Figure size in inches

    Returns:
        Tuple of (matplotlib Figure object, GroundReceptionStats)
    """
    if map_utils is None:
        map_utils = MapUtils()

    fig, ax = plt.subplots(figsize=(size, size))
    ax.set_aspect('equal')

    # Convert all ground points to mercator coordinates
    ground_x, ground_y = map_utils.to_mercator_xy(ground_points['lat'].values, ground_points['lon'].values)

    # Plot all ground points
    ax.scatter(ground_x, ground_y, color='red', s=50, alpha=0.6, marker='o', label='Ground points')

    # Calculate weighted average of lat/lon (equal weights for now)
    avg_lat = ground_points['lat'].mean()
    avg_lon = ground_points['lon'].mean()
    avg_x, avg_y = map_utils.to_mercator_xy(avg_lat, avg_lon)

    # Plot the weighted average point
    ax.scatter(avg_x, avg_y, color='blue', s=200, alpha=0.8, marker='*',
               label='Weighted average', edgecolors='black', linewidths=2, zorder=5)

    # Calculate standard deviation in both degrees and meters
    std_dev_lat = ground_points['lat'].std()
    std_dev_lon = ground_points['lon'].std()

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
    ground_elev = get_elevation(avg_lat, avg_lon)

    # Create statistics object
    stats = GroundReceptionStats(
        avg_lat=avg_lat,
        avg_lon=avg_lon,
        num_points=len(ground_points),
        std_dev_lat=std_dev_lat,
        std_dev_lon=std_dev_lon,
        std_dev_x=std_dev_x,
        std_dev_y=std_dev_y,
        std_dev_combined=std_dev_combined,
        avg_alt=avg_alt,
        std_dev_alt=std_dev_alt,
        ground_elev=ground_elev
    )

    # Prepare list of points for map limits calculation
    map_limits = [[lat, lon] for lat, lon in zip(ground_points['lat'], ground_points['lon'])]

    # Find the limits of the map
    min_x, min_y, max_x, max_y, zoom = map_utils.get_map_limits(map_limits)
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)

    cx.add_basemap(
        ax,
        zoom=zoom,
        crs='EPSG:3857',
        source=cx.providers.OpenStreetMap.Mapnik,
    )

    # Set up axes with tick marks in meters
    # Use the weighted average as the origin point for relative distances
    def mercator_to_meters_x(x, p):
        """Convert mercator x coordinate to meters from average point."""
        return int(x - avg_x)

    def mercator_to_meters_y(y, p):
        """Convert mercator y coordinate to meters from average point."""
        return int(y - avg_y)

    # Create secondary axes showing distances in meters
    ax.set_xlabel('East-West distance from average (m)', fontsize=10)
    ax.set_ylabel('North-South distance from average (m)', fontsize=10)

    # Format the tick labels to show meters
    ax.xaxis.set_major_formatter(FuncFormatter(mercator_to_meters_x))
    ax.yaxis.set_major_formatter(FuncFormatter(mercator_to_meters_y))

    # Add grid for easier reading
    ax.grid(True, alpha=0.3, linestyle='--', linewidth=0.5)

    # Add text box at the top with statistics
    stats_text = f"Weighted Average: {avg_lat:.6f}, {avg_lon:.6f}\n"
    stats_text += f"Std Dev: E-W {std_dev_x:.1f}m, N-S {std_dev_y:.1f}m, Combined {std_dev_combined:.1f}m\n"
    stats_text += f"Altitude: {avg_alt:.1f}m (±{std_dev_alt:.1f}m)"
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

    return fig, stats
