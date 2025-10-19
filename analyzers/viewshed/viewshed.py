#!/usr/bin/env python3

"""
Viewshed Analysis Tool for Sonde Receiver Antenna Planning

Given a lat/lon location and antenna height, computes and visualizes the area
reachable by line-of-sight from that location. Useful for planning optimal
antenna deployment locations for sonde receivers.

The tool:
1. Creates a grid of points around the antenna location
2. Fetches elevation data for each grid point
3. Calculates line-of-sight visibility using terrain elevation
4. Visualizes the viewshed on a map

Usage:
    ./viewshed.py --lat 47.6 --lon -122.3 --height 10 --radius 50
"""

from geographiclib.geodesic import Geodesic
from pyproj import Transformer
import argparse
import contextily as cx
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os
import requests
import sys
import time
from matplotlib.patches import Circle
from matplotlib.colors import LinearSegmentedColormap
from pathlib import Path

# Import DEM manager for local elevation data
sys.path.insert(0, os.path.dirname(__file__))
from dem_manager import DEMManager

matplotlib.use('Agg')

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

# Constants
EARTH_RADIUS_M = 6371000  # Earth radius in meters
METERS_PER_KM = 1000
METERS_PER_MILE = 1609.34

# National Map Elevation API
ELEVATION_API_URL = 'https://epqs.nationalmap.gov/v1/json'

# Coordinate transformations
wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
mercator_to_wgs84 = Transformer.from_crs(crs_from='EPSG:3857', crs_to='EPSG:4326')


def to_mercator_xy(lat, lon):
    """Convert WGS84 lat/lon to Web Mercator x/y"""
    return wgs84_to_mercator.transform(lat, lon)


def to_wgs84(x, y):
    """Convert Web Mercator x/y to WGS84 lat/lon"""
    return mercator_to_wgs84.transform(x, y)


def get_elevation(lat, lon, cache=None, dem_manager=None, dem_file=None):
    """
    Fetch ground elevation at a given lat/lon.

    Can use either local DEM tiles (preferred) or USGS National Map API (fallback).

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        cache: Optional dict to cache results
        dem_manager: Optional DEMManager instance for local DEM tiles
        dem_file: Optional path to DEM file (used with dem_manager)

    Returns:
        Elevation in meters, or None if unavailable
    """
    if cache is not None:
        key = (round(lat, 6), round(lon, 6))
        if key in cache:
            return cache[key]

    elev = None

    # Try local DEM first if available
    if dem_manager is not None:
        try:
            elev = dem_manager.get_elevation(lat, lon, dem_file)
        except Exception as e:
            print(f"Warning: DEM lookup failed for {lat},{lon}: {e}")
            elev = None

    # Fallback to API if DEM unavailable
    if elev is None and dem_manager is None:
        try:
            resp = requests.get(ELEVATION_API_URL, params={
                'x': lon,
                'y': lat,
                'units': 'Meters',
                'wkid': '4326',
            }, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            # Extract elevation value
            if 'value' in data and data['value'] is not None:
                elev = float(data['value'])
        except Exception as e:
            print(f"Warning: Failed to get elevation for {lat},{lon}: {e}")

    if cache is not None and elev is not None:
        cache[key] = elev

    return elev


def compute_point_at_bearing_distance(lat, lon, bearing_deg, distance_m):
    """
    Compute lat/lon of a point at a given bearing and distance from origin.

    Args:
        lat: Origin latitude in decimal degrees
        lon: Origin longitude in decimal degrees
        bearing_deg: Bearing in degrees (0=north, 90=east)
        distance_m: Distance in meters

    Returns:
        Tuple of (lat, lon) in decimal degrees
    """
    result = Geodesic.WGS84.Direct(lat, lon, bearing_deg, distance_m)
    return result['lat2'], result['lon2']


def is_visible(observer_lat, observer_lon, observer_elevation_agl,
               target_lat, target_lon, target_elevation_msl,
               observer_elevation_msl, num_samples=20,
               dem_manager=None, dem_file=None, debug=False):
    """
    Determine if a target location is visible from an observer location.

    Uses Fresnel zone clearance - checks if terrain between observer and target
    blocks the line of sight.

    Args:
        observer_lat, observer_lon: Observer position
        observer_elevation_agl: Observer antenna height above ground (meters)
        target_lat, target_lon: Target position
        target_elevation_msl: Target ground elevation MSL (meters)
        observer_elevation_msl: Observer ground elevation MSL (meters)
        num_samples: Number of intermediate points to check for obstruction
        dem_manager: Optional DEMManager instance
        dem_file: Optional DEM file path
        debug: If True, print debug information

    Returns:
        Boolean indicating if target is visible
    """
    # Calculate total observer elevation MSL
    observer_total_msl = observer_elevation_msl + observer_elevation_agl

    # Get distance between observer and target
    geo = Geodesic.WGS84.Inverse(observer_lat, observer_lon, target_lat, target_lon)
    total_distance_m = geo['s12']

    # If target is extremely close, assume visible
    if total_distance_m < 10:
        return True

    if debug:
        print(f"\n=== Visibility Check ===")
        print(f"Observer: {observer_lat:.4f}, {observer_lon:.4f}")
        print(f"  Ground elev: {observer_elevation_msl:.1f}m")
        print(f"  Antenna AGL: {observer_elevation_agl:.1f}m")
        print(f"  Total MSL: {observer_total_msl:.1f}m")
        print(f"Target: {target_lat:.4f}, {target_lon:.4f}")
        print(f"  Ground elev: {target_elevation_msl:.1f}m")
        print(f"  Distance: {total_distance_m/1000:.2f}km")

    # Calculate the required elevation along the line of sight at each sample point
    # accounting for Earth's curvature
    for i in range(1, num_samples):
        # Distance from observer to this sample point
        sample_distance_m = (i / num_samples) * total_distance_m

        # Compute lat/lon of sample point along the great circle
        bearing = geo['azi1']
        sample_lat, sample_lon = compute_point_at_bearing_distance(
            observer_lat, observer_lon, bearing, sample_distance_m)

        # Get elevation at sample point
        sample_elevation = get_elevation(sample_lat, sample_lon,
                                        dem_manager=dem_manager, dem_file=dem_file)
        if sample_elevation is None:
            # No elevation data (likely water or out of bounds)
            # Treat as sea level (0m) for visibility purposes
            sample_elevation = 0.0
            if debug:
                print(f"  Sample {i}: No elevation data - assuming sea level (0m)")

        # Calculate the line-of-sight elevation at this distance
        # Linear interpolation from observer to target
        fraction = sample_distance_m / total_distance_m
        los_elevation = observer_total_msl + fraction * (target_elevation_msl - observer_total_msl)

        # Account for Earth curvature - terrain drops away as we go further
        # Curvature correction: h = d^2 / (2*R) where d is distance, R is Earth radius
        curvature_drop = (sample_distance_m ** 2) / (2 * EARTH_RADIUS_M)
        los_elevation_corrected = los_elevation + curvature_drop

        # Check if terrain obstructs the line of sight
        # We add a small clearance margin (10m) for Fresnel zone
        if sample_elevation > (los_elevation_corrected - 10):
            if debug:
                print(f"  Sample {i} at {sample_distance_m/1000:.1f}km:")
                print(f"    Terrain elev: {sample_elevation:.1f}m")
                print(f"    LOS elev (corrected): {los_elevation_corrected:.1f}m")
                print(f"    BLOCKED!")
            return False

    if debug:
        print(f"  Result: VISIBLE")
    return True


def compute_viewshed(observer_lat, observer_lon, observer_height_agl,
                     radius_km, resolution_km=1.0, num_radials=36,
                     use_local_dem=True, dem_product='SRTM3', grid_points=25):
    """
    Compute viewshed from an observer location.

    Creates a rectilinear grid of points and determines visibility for each.

    Args:
        observer_lat, observer_lon: Observer location
        observer_height_agl: Observer antenna height above ground (meters)
        radius_km: Maximum radius to analyze (km)
        resolution_km: (Deprecated, kept for backwards compatibility)
        num_radials: (Deprecated, kept for backwards compatibility)
        grid_points: Number of grid points in each direction (creates grid_points x grid_points grid)
        use_local_dem: If True, download and use local DEM tiles (much faster)
        dem_product: 'SRTM1' (30m res) or 'SRTM3' (90m res)

    Returns:
        Dictionary with:
            - 'visible_points': List of (lat, lon) tuples that are visible
            - 'blocked_points': List of (lat, lon) tuples that are blocked
            - 'observer_elevation': Observer ground elevation MSL
            - 'max_range_km': Maximum visible range found
    """
    print(f"Computing viewshed for {observer_lat:.4f}, {observer_lon:.4f}")
    print(f"  Antenna height: {observer_height_agl}m AGL")
    print(f"  Analysis radius: {radius_km}km")
    print(f"  Grid size: {grid_points}x{grid_points} points")

    # Setup DEM manager if using local tiles
    dem_manager = None
    dem_file = None
    if use_local_dem:
        print(f"  Using local DEM tiles ({dem_product})")
        dem_manager = DEMManager()

        # Calculate bounding box for the analysis area
        # Add padding to ensure coverage
        padding_km = radius_km * 0.1
        total_radius = radius_km + padding_km

        # Approximate conversion: 1 degree ≈ 111 km at equator
        lat_offset = total_radius / 111.0
        lon_offset = total_radius / (111.0 * np.cos(np.radians(observer_lat)))

        min_lat = observer_lat - lat_offset
        max_lat = observer_lat + lat_offset
        min_lon = observer_lon - lon_offset
        max_lon = observer_lon + lon_offset

        # Download DEM tiles for the area
        dem_file = dem_manager.download_tiles_for_bounds(
            min_lat, min_lon, max_lat, max_lon, product=dem_product)
    else:
        print("  Using USGS National Map API (slower, US-only)")

    # Get observer elevation
    print("  Fetching observer elevation...")
    observer_elevation_msl = get_elevation(observer_lat, observer_lon,
                                          dem_manager=dem_manager, dem_file=dem_file)
    if observer_elevation_msl is None:
        print("  ERROR: Could not determine observer elevation")
        if dem_manager:
            dem_manager.cleanup()
        return None
    print(f"  Observer ground elevation: {observer_elevation_msl:.1f}m MSL")

    # Create rectilinear grid with fixed number of points
    # Calculate grid bounds (square box around observer)
    # 1 degree latitude ≈ 111 km
    lat_radius = radius_km / 111.0
    lon_radius = radius_km / (111.0 * np.cos(np.radians(observer_lat)))

    # Generate grid points - fixed count regardless of radius
    lat_values = np.linspace(observer_lat - lat_radius, observer_lat + lat_radius, grid_points)
    lon_values = np.linspace(observer_lon - lon_radius, observer_lon + lon_radius, grid_points)

    total_points = grid_points * grid_points - 1  # -1 to exclude observer point
    print(f"  Testing up to {total_points} points on {grid_points}x{grid_points} grid...")

    visible_points = []
    blocked_points = []
    max_visible_range_km = 0

    # Test each point on the grid
    elevation_cache = {}
    point_count = 0

    for target_lat in lat_values:
        for target_lon in lon_values:
            # Skip observer location (very close to observer)
            if abs(target_lat - observer_lat) < 1e-6 and abs(target_lon - observer_lon) < 1e-6:
                continue

            point_count += 1

            # Show progress
            if point_count % 100 == 0:
                print(f"    Progress: {point_count}/{total_points} points", end='\r')

            # Calculate distance from observer to determine if within radius
            from geographiclib.geodesic import Geodesic
            geod = Geodesic.WGS84
            result = geod.Inverse(observer_lat, observer_lon, target_lat, target_lon)
            distance_m = result['s12']
            distance_km = distance_m / METERS_PER_KM

            # Skip points outside the circular radius
            if distance_km > radius_km:
                continue

            # Get target elevation
            target_elevation = get_elevation(target_lat, target_lon, cache=elevation_cache,
                                            dem_manager=dem_manager, dem_file=dem_file)
            if target_elevation is None:
                # No elevation data (likely water) - assume sea level
                target_elevation = 0.0

            # Check visibility
            if is_visible(observer_lat, observer_lon, observer_height_agl,
                         target_lat, target_lon, target_elevation, observer_elevation_msl,
                         dem_manager=dem_manager, dem_file=dem_file):
                visible_points.append((target_lat, target_lon))
                max_visible_range_km = max(max_visible_range_km, distance_km)
            else:
                blocked_points.append((target_lat, target_lon))

            # Rate limiting only needed for API
            if not use_local_dem:
                time.sleep(0.05)

    print(f"\n  Complete! {len(visible_points)} visible, {len(blocked_points)} blocked")
    print(f"  Maximum visible range: {max_visible_range_km:.1f}km")

    # Cleanup DEM manager
    if dem_manager:
        dem_manager.cleanup()

    return {
        'visible_points': visible_points,
        'blocked_points': blocked_points,
        'observer_elevation': observer_elevation_msl,
        'observer_height_agl': observer_height_agl,
        'max_range_km': max_visible_range_km,
    }


def plot_viewshed(observer_lat, observer_lon, viewshed_data, output_file='viewshed.png'):
    """
    Visualize viewshed on a map.

    Args:
        observer_lat, observer_lon: Observer location
        viewshed_data: Dictionary returned by compute_viewshed()
        output_file: Output filename for the plot
    """
    print(f"\nGenerating viewshed visualization...")

    visible_points = viewshed_data['visible_points']
    blocked_points = viewshed_data['blocked_points']

    # Create figure
    fig, ax = plt.subplots(figsize=(20, 20))

    # Convert observer to mercator
    obs_x, obs_y = to_mercator_xy(observer_lat, observer_lon)

    # Plot blocked areas (grey)
    if blocked_points:
        blocked_lats, blocked_lons = zip(*blocked_points)
        blocked_x, blocked_y = to_mercator_xy(blocked_lats, blocked_lons)
        ax.scatter(blocked_x, blocked_y, c='grey', alpha=0.3, s=50, marker='s',
                  label='Blocked by terrain')

    # Plot visible areas (green)
    if visible_points:
        visible_lats, visible_lons = zip(*visible_points)
        visible_x, visible_y = to_mercator_xy(visible_lats, visible_lons)
        ax.scatter(visible_x, visible_y, c='green', alpha=0.5, s=50, marker='o',
                  label='Line-of-sight visible')

    # Plot observer location (red star)
    ax.scatter(obs_x, obs_y, c='red', s=500, marker='*',
              label=f'Antenna ({viewshed_data["observer_height_agl"]}m AGL)',
              zorder=10, edgecolors='black', linewidths=2)

    # Add basemap
    print("  Downloading basemap tiles...")
    cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, zoom='auto')

    # Labels and legend
    ax.set_title(
        f'Viewshed Analysis: {observer_lat:.4f}°, {observer_lon:.4f}°\n'
        f'Antenna: {viewshed_data["observer_height_agl"]}m AGL '
        f'(Ground: {viewshed_data["observer_elevation"]:.0f}m MSL)\n'
        f'Max visible range: {viewshed_data["max_range_km"]:.1f}km',
        fontsize=16, pad=20
    )
    ax.legend(loc='upper right', fontsize=12)
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)

    # Save
    fig.tight_layout()
    print(f"  Saving to {output_file}...")
    fig.savefig(output_file, bbox_inches='tight', dpi=150)
    print(f"  Done!")

    return output_file


def main():
    parser = argparse.ArgumentParser(
        description='Compute and visualize viewshed for antenna placement planning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic viewshed with 10m antenna, 50km radius
  %(prog)s --lat 47.6 --lon -122.3 --height 10 --radius 50

  # High-resolution analysis with 20m tower
  %(prog)s --lat 47.6 --lon -122.3 --height 20 --radius 100 --resolution 0.5 --radials 72

  # Quick low-resolution preview
  %(prog)s --lat 47.6 --lon -122.3 --height 10 --radius 30 --resolution 2 --radials 24
        """
    )

    parser.add_argument(
        '--lat',
        type=float,
        required=True,
        help='Latitude of antenna location (decimal degrees)'
    )
    parser.add_argument(
        '--lon',
        type=float,
        required=True,
        help='Longitude of antenna location (decimal degrees)'
    )
    parser.add_argument(
        '--height',
        type=float,
        required=True,
        help='Antenna height above ground level (meters)'
    )
    parser.add_argument(
        '--radius',
        type=float,
        default=50,
        help='Analysis radius (km, default: 50)'
    )
    parser.add_argument(
        '--resolution',
        type=float,
        default=1.0,
        help='Radial resolution - spacing between range rings (km, default: 1.0)'
    )
    parser.add_argument(
        '--radials',
        type=int,
        default=36,
        help='Number of radial bearings to test (default: 36, i.e., every 10 degrees)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='viewshed.png',
        help='Output filename (default: viewshed.png)'
    )
    parser.add_argument(
        '--use-api',
        action='store_true',
        default=False,
        help='Use USGS API instead of local DEM tiles (slower, US-only)'
    )
    parser.add_argument(
        '--dem-product',
        type=str,
        choices=['SRTM1', 'SRTM3'],
        default='SRTM3',
        help='DEM product: SRTM1 (30m resolution) or SRTM3 (90m resolution, default)'
    )

    args = parser.parse_args()

    # Validate inputs
    if not (-90 <= args.lat <= 90):
        print("Error: Latitude must be between -90 and 90")
        return 1
    if not (-180 <= args.lon <= 180):
        print("Error: Longitude must be between -180 and 180")
        return 1
    if args.height <= 0:
        print("Error: Antenna height must be positive")
        return 1
    if args.radius <= 0:
        print("Error: Radius must be positive")
        return 1

    # Compute viewshed
    print("=" * 70)
    print("VIEWSHED ANALYSIS FOR SONDE RECEIVER ANTENNA PLACEMENT")
    print("=" * 70)

    viewshed = compute_viewshed(
        args.lat, args.lon, args.height,
        args.radius, args.resolution, args.radials,
        use_local_dem=not args.use_api,
        dem_product=args.dem_product
    )

    if viewshed is None:
        print("Error: Viewshed computation failed")
        return 1

    # Plot results
    plot_viewshed(args.lat, args.lon, viewshed, args.output)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Observer: {args.lat:.4f}°, {args.lon:.4f}°")
    print(f"  Ground elevation: {viewshed['observer_elevation']:.1f}m MSL")
    print(f"  Antenna height: {viewshed['observer_height_agl']:.1f}m AGL")
    print(f"  Total antenna elevation: {viewshed['observer_elevation'] + viewshed['observer_height_agl']:.1f}m MSL")
    print(f"  Visible points: {len(viewshed['visible_points'])}")
    print(f"  Blocked points: {len(viewshed['blocked_points'])}")
    total = len(viewshed['visible_points']) + len(viewshed['blocked_points'])
    if total > 0:
        pct = 100 * len(viewshed['visible_points']) / total
        print(f"  Visibility: {pct:.1f}%")
    print(f"  Maximum visible range: {viewshed['max_range_km']:.1f}km")
    print(f"  Output saved to: {args.output}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
