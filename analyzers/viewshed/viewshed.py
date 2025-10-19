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

# Coordinate transformations
wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
mercator_to_wgs84 = Transformer.from_crs(crs_from='EPSG:3857', crs_to='EPSG:4326')


def to_mercator_xy(lat, lon):
    """Convert WGS84 lat/lon to Web Mercator x/y"""
    return wgs84_to_mercator.transform(lat, lon)


def to_wgs84(x, y):
    """Convert Web Mercator x/y to WGS84 lat/lon"""
    return mercator_to_wgs84.transform(x, y)


def get_elevation(lat, lon, cache=None, dem_manager=None, dem_file=None, dem_file_fallback=None):
    """
    Fetch ground elevation at a given lat/lon.

    Can use either local DEM tiles (preferred) or USGS National Map API (fallback).

    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        cache: Optional dict to cache results
        dem_manager: Optional DEMManager instance for local DEM tiles
        dem_file: Optional path to DEM file (used with dem_manager)
        dem_file_fallback: Optional fallback DEM file (for SRTM_BEST mode)

    Returns:
        Elevation in meters, or None if unavailable
    """
    if cache is not None:
        key = (round(lat, 6), round(lon, 6))
        if key in cache:
            return cache[key]

    elev = None

    # Use local DEM (required - no API fallback)
    if dem_manager is not None:
        try:
            elev = dem_manager.get_elevation(lat, lon, dem_file, dem_file_fallback)
        except Exception as e:
            print(f"Warning: DEM lookup failed for {lat},{lon}: {e}")
            elev = None
    else:
        print(f"Warning: No DEM manager provided for elevation lookup at {lat},{lon}")

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
               dem_manager=None, dem_file=None, dem_file_fallback=None, debug=False):
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
                                        dem_manager=dem_manager, dem_file=dem_file,
                                        dem_file_fallback=dem_file_fallback)
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
                     use_local_dem=True, dem_product='SRTM3', grid_points=25,
                     progress_callback=None):
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
        progress_callback: Optional function(completed, total, message) to report progress

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
        # Use environment variable for cache dir if set, otherwise use default
        cache_dir = os.environ.get('ELEVATION_CACHE_DIR', '~/.cache/srtm')
        dem_manager = DEMManager(cache_dir=cache_dir)

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

        # Handle SRTM_BEST mode (returns tuple of two DEM files)
        dem_file_fallback = None
        if isinstance(dem_file, tuple):
            dem_file, dem_file_fallback = dem_file
    else:
        print("  Using USGS National Map API (slower, US-only)")
        dem_file_fallback = None

    # Get observer elevation
    print("  Fetching observer elevation...")
    observer_elevation_msl = get_elevation(observer_lat, observer_lon,
                                          dem_manager=dem_manager, dem_file=dem_file,
                                          dem_file_fallback=dem_file_fallback)
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
                if progress_callback:
                    progress_callback(point_count, total_points, f"Testing point {point_count}/{total_points}")

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
                                            dem_manager=dem_manager, dem_file=dem_file,
                                            dem_file_fallback=dem_file_fallback)
            if target_elevation is None:
                # No elevation data (likely water) - assume sea level
                target_elevation = 0.0

            # Check visibility
            if is_visible(observer_lat, observer_lon, observer_height_agl,
                         target_lat, target_lon, target_elevation, observer_elevation_msl,
                         dem_manager=dem_manager, dem_file=dem_file, dem_file_fallback=dem_file_fallback):
                visible_points.append((target_lat, target_lon))
                max_visible_range_km = max(max_visible_range_km, distance_km)
            else:
                blocked_points.append((target_lat, target_lon))

            # Rate limiting only needed for API
            if not use_local_dem:
                time.sleep(0.05)

    print(f"\n  Complete! {len(visible_points)} visible, {len(blocked_points)} blocked")
    print(f"  Maximum visible range: {max_visible_range_km:.1f}km")

    # Get DEM statistics if using SRTM_BEST
    dem_stats = None
    if dem_manager and dem_product == 'SRTM_BEST':
        dem_stats = dem_manager.stats.copy()
        srtm1_pct = (dem_stats['srtm1_queries'] / dem_stats['total_queries'] * 100) if dem_stats['total_queries'] > 0 else 0
        srtm3_pct = (dem_stats['srtm3_fallback_queries'] / dem_stats['total_queries'] * 100) if dem_stats['total_queries'] > 0 else 0
        print(f"\n  DEM Resolution Statistics:")
        print(f"    SRTM1 (30m): {dem_stats['srtm1_queries']} queries ({srtm1_pct:.1f}%)")
        print(f"    SRTM3 (90m fallback): {dem_stats['srtm3_fallback_queries']} queries ({srtm3_pct:.1f}%)")
        print(f"    Total: {dem_stats['total_queries']} queries")

    # Cleanup DEM manager
    if dem_manager:
        dem_manager.cleanup()

    result = {
        'visible_points': visible_points,
        'blocked_points': blocked_points,
        'observer_elevation': observer_elevation_msl,
        'observer_height_agl': observer_height_agl,
        'max_range_km': max_visible_range_km,
    }

    if dem_stats:
        result['dem_stats'] = dem_stats

    return result


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


def compute_coverage(observer_lat, observer_lon, observer_height_agl,
                     target_points, dem_manager=None, dem_file=None, dem_file_fallback=None):
    """
    Compute what fraction of target points are visible from an observer location.

    This is different from compute_viewshed - instead of computing a radial grid
    around the observer, this tests visibility to a fixed set of target points.
    Useful for coverage optimization.

    Args:
        observer_lat, observer_lon: Observer location
        observer_height_agl: Observer antenna height above ground (meters)
        target_points: List of (lat, lon) tuples to test visibility to
        dem_manager: Optional DEMManager instance
        dem_file: Optional DEM file path
        dem_file_fallback: Optional fallback DEM file path

    Returns:
        Dictionary with:
            - 'visible_count': Number of target points visible
            - 'total_count': Total number of target points
            - 'coverage_pct': Percentage of target points visible
            - 'visible_indices': List of indices of visible points
            - 'observer_elevation': Observer ground elevation MSL
    """
    # Get observer elevation
    observer_elevation_msl = get_elevation(observer_lat, observer_lon,
                                          dem_manager=dem_manager, dem_file=dem_file,
                                          dem_file_fallback=dem_file_fallback)
    if observer_elevation_msl is None:
        # Can't determine elevation - return zero coverage
        return {
            'visible_count': 0,
            'total_count': len(target_points),
            'coverage_pct': 0.0,
            'visible_indices': [],
            'observer_elevation': None
        }

    visible_indices = []
    elevation_cache = {}

    for idx, (target_lat, target_lon) in enumerate(target_points):
        # Get target elevation
        target_elevation = get_elevation(target_lat, target_lon, cache=elevation_cache,
                                        dem_manager=dem_manager, dem_file=dem_file,
                                        dem_file_fallback=dem_file_fallback)
        if target_elevation is None:
            target_elevation = 0.0  # Assume sea level for water/missing data

        # Check visibility
        if is_visible(observer_lat, observer_lon, observer_height_agl,
                     target_lat, target_lon, target_elevation, observer_elevation_msl,
                     dem_manager=dem_manager, dem_file=dem_file, dem_file_fallback=dem_file_fallback):
            visible_indices.append(idx)

    visible_count = len(visible_indices)
    total_count = len(target_points)
    coverage_pct = 100.0 * visible_count / total_count if total_count > 0 else 0.0

    return {
        'visible_count': visible_count,
        'total_count': total_count,
        'coverage_pct': coverage_pct,
        'visible_indices': visible_indices,
        'observer_elevation': observer_elevation_msl
    }


def optimize_coverage(target_bounds, search_bounds, observer_height_agl,
                     target_grid_size=20, search_grid_size=10,
                     top_k=5, hill_climb_steps=10,
                     dem_product='SRTM3', progress_callback=None):
    """
    Find optimal observer locations to maximize coverage of a target area.

    Strategy:
    1. Create fixed grid of points in target area
    2. Do coarse grid search over search area
    3. Hill climb from top k candidates

    Args:
        target_bounds: Dict with 'min_lat', 'max_lat', 'min_lon', 'max_lon' for target area
        search_bounds: Dict with 'min_lat', 'max_lat', 'min_lon', 'max_lon' for search area
        observer_height_agl: Observer antenna height above ground (meters)
        target_grid_size: Number of target points in each direction (creates NxN grid)
        search_grid_size: Number of search points in each direction for coarse search
        top_k: Number of top candidates to hill climb from
        hill_climb_steps: Number of hill climbing iterations per candidate
        dem_product: 'SRTM1' or 'SRTM3'
        progress_callback: Optional function(completed, total, message) to report progress

    Returns:
        Dictionary with:
            - 'best_location': (lat, lon) of best observer location
            - 'best_coverage_pct': Coverage percentage at best location
            - 'all_candidates': List of all evaluated locations with scores
            - 'target_points': List of target points used
    """
    print(f"Optimizing coverage for target area...")
    print(f"  Target grid: {target_grid_size}x{target_grid_size} points")
    print(f"  Search grid: {search_grid_size}x{search_grid_size} initial candidates")
    print(f"  Hill climbing from top {top_k} candidates")

    # Calculate total estimated steps
    coarse_search_steps = search_grid_size * search_grid_size
    # Hill climbing: estimate 8 neighbors per step, but may converge early
    hill_climb_steps_estimate = top_k * hill_climb_steps * 8
    total_steps_estimate = coarse_search_steps + hill_climb_steps_estimate
    completed_steps = 0

    def report_progress(message):
        nonlocal completed_steps
        if progress_callback:
            progress_callback(completed_steps, total_steps_estimate, message)

    # Setup DEM manager
    dem_manager = DEMManager()

    # Download DEM tiles for entire area (target + search)
    all_min_lat = min(target_bounds['min_lat'], search_bounds['min_lat'])
    all_max_lat = max(target_bounds['max_lat'], search_bounds['max_lat'])
    all_min_lon = min(target_bounds['min_lon'], search_bounds['min_lon'])
    all_max_lon = max(target_bounds['max_lon'], search_bounds['max_lon'])

    # Add padding
    lat_padding = (all_max_lat - all_min_lat) * 0.1
    lon_padding = (all_max_lon - all_min_lon) * 0.1

    dem_file = dem_manager.download_tiles_for_bounds(
        all_min_lat - lat_padding, all_min_lon - lon_padding,
        all_max_lat + lat_padding, all_max_lon + lon_padding,
        product=dem_product)

    # Create fixed target grid
    print("  Creating target point grid...")
    target_lats = np.linspace(target_bounds['min_lat'], target_bounds['max_lat'], target_grid_size)
    target_lons = np.linspace(target_bounds['min_lon'], target_bounds['max_lon'], target_grid_size)
    target_points = [(lat, lon) for lat in target_lats for lon in target_lons]
    print(f"  Target points: {len(target_points)}")

    # Coarse grid search
    print("  Running coarse grid search...")
    search_lats = np.linspace(search_bounds['min_lat'], search_bounds['max_lat'], search_grid_size)
    search_lons = np.linspace(search_bounds['min_lon'], search_bounds['max_lon'], search_grid_size)

    candidates = []  # List of (lat, lon, coverage_pct)
    total_search = search_grid_size * search_grid_size
    count = 0

    report_progress("Starting coarse grid search...")

    for lat in search_lats:
        for lon in search_lons:
            count += 1
            if count % 10 == 0:
                print(f"    Progress: {count}/{total_search} candidates", end='\r')

            result = compute_coverage(lat, lon, observer_height_agl, target_points,
                                     dem_manager=dem_manager, dem_file=dem_file)
            candidates.append((lat, lon, result['coverage_pct']))

            completed_steps += 1
            report_progress(f"Coarse search: {count}/{total_search} candidates")

    print(f"\n  Coarse search complete. Best so far: {max(c[2] for c in candidates):.1f}%")

    # Sort and take top k
    candidates.sort(key=lambda x: x[2], reverse=True)
    top_candidates = candidates[:top_k]

    print(f"  Top {top_k} candidates:")
    for i, (lat, lon, cov) in enumerate(top_candidates):
        print(f"    {i+1}. ({lat:.4f}, {lon:.4f}): {cov:.1f}%")

    # Hill climbing from each top candidate
    print(f"  Hill climbing ({hill_climb_steps} steps per candidate)...")

    # Estimate step size based on search area
    lat_step = (search_bounds['max_lat'] - search_bounds['min_lat']) / (search_grid_size * 2)
    lon_step = (search_bounds['max_lon'] - search_bounds['min_lon']) / (search_grid_size * 2)

    best_overall = None
    best_coverage = 0

    for candidate_idx, (start_lat, start_lon, start_cov) in enumerate(top_candidates):
        print(f"    Climbing from candidate {candidate_idx+1}...")
        current_lat, current_lon = start_lat, start_lon
        current_cov = start_cov

        report_progress(f"Hill climbing: candidate {candidate_idx+1}/{top_k}")

        for step in range(hill_climb_steps):
            # Try all 8 neighbors plus staying put (reduce step size each iteration)
            step_scale = 1.0 / (1 + step * 0.2)  # Gradually reduce step size
            current_lat_step = lat_step * step_scale
            current_lon_step = lon_step * step_scale

            neighbors = [
                (current_lat + current_lat_step, current_lon),  # N
                (current_lat - current_lat_step, current_lon),  # S
                (current_lat, current_lon + current_lon_step),  # E
                (current_lat, current_lon - current_lon_step),  # W
                (current_lat + current_lat_step, current_lon + current_lon_step),  # NE
                (current_lat + current_lat_step, current_lon - current_lon_step),  # NW
                (current_lat - current_lat_step, current_lon + current_lon_step),  # SE
                (current_lat - current_lat_step, current_lon - current_lon_step),  # SW
            ]

            # Filter to stay within search bounds
            neighbors = [(lat, lon) for lat, lon in neighbors
                        if search_bounds['min_lat'] <= lat <= search_bounds['max_lat']
                        and search_bounds['min_lon'] <= lon <= search_bounds['max_lon']]

            # Evaluate neighbors
            best_neighbor = None
            best_neighbor_cov = current_cov

            for lat, lon in neighbors:
                result = compute_coverage(lat, lon, observer_height_agl, target_points,
                                         dem_manager=dem_manager, dem_file=dem_file)
                if result['coverage_pct'] > best_neighbor_cov:
                    best_neighbor = (lat, lon)
                    best_neighbor_cov = result['coverage_pct']

                completed_steps += 1
                report_progress(f"Hill climbing: candidate {candidate_idx+1}/{top_k}, step {step+1}/{hill_climb_steps}")

            # Move to best neighbor if better, otherwise stop
            if best_neighbor is not None:
                current_lat, current_lon = best_neighbor
                current_cov = best_neighbor_cov
            else:
                # No improvement found, stop climbing - add remaining steps to completed count
                remaining = (hill_climb_steps - step - 1) * 8
                completed_steps += remaining
                break

        print(f"      Final: ({current_lat:.4f}, {current_lon:.4f}): {current_cov:.1f}%")

        # Track overall best
        if current_cov > best_coverage:
            best_overall = (current_lat, current_lon)
            best_coverage = current_cov

    # Cleanup
    dem_manager.cleanup()

    print(f"\n  Optimization complete!")
    print(f"  Best location: ({best_overall[0]:.4f}, {best_overall[1]:.4f})")
    print(f"  Coverage: {best_coverage:.1f}%")

    return {
        'best_location': best_overall,
        'best_coverage_pct': best_coverage,
        'all_candidates': candidates,
        'target_points': target_points
    }


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
