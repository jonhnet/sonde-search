#!/usr/bin/env python3

"""
DEM (Digital Elevation Model) Tile Manager

Handles downloading and reading SRTM elevation data for viewshed analysis.
Uses the 'elevation' library to automatically download SRTM tiles and
'rasterio' to read elevation values.

SRTM (Shuttle Radar Topography Mission) provides ~30m resolution global
elevation data (90m outside US).

Usage:
    from dem_manager import DEMManager

    dem = DEMManager(cache_dir='~/.cache/srtm')
    elevation = dem.get_elevation(47.6, -122.3)
"""

import os
import numpy as np
from pathlib import Path
import rasterio
from rasterio.windows import from_bounds

# Import elevation library and override its cache directory
import elevation
import elevation.datasource

# Override elevation library's cache directory to respect ELEVATION_CACHE_DIR env var
if 'ELEVATION_CACHE_DIR' in os.environ:
    elevation.datasource.CACHE_DIR = os.environ['ELEVATION_CACHE_DIR']


class DEMManager:
    """
    Manages DEM tile downloads and elevation queries.

    Automatically downloads SRTM tiles as needed and caches them locally.
    """

    def __init__(self, cache_dir='~/.cache/srtm'):
        """
        Initialize DEM manager.

        Args:
            cache_dir: Directory to store downloaded DEM tiles
        """
        self.cache_dir = Path(os.path.expanduser(cache_dir))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Keep track of loaded raster datasets to avoid reopening
        self._raster_cache = {}

        # Track DEM resolution statistics (for SRTM_BEST mode)
        self.stats = {
            'srtm1_queries': 0,  # Successful SRTM1 queries
            'srtm3_fallback_queries': 0,  # Had to fall back to SRTM3
            'total_queries': 0
        }

        # Override elevation library cache directory to match our cache_dir
        # This ensures the elevation library's raw tile cache goes to the same location
        elevation.datasource.CACHE_DIR = str(self.cache_dir)

        print(f"DEM cache directory: {self.cache_dir}")

    def download_tiles_for_bounds(self, min_lat, min_lon, max_lat, max_lon,
                                   product='SRTM3', progress_callback=None):
        """
        Download DEM tiles covering a bounding box.

        Args:
            min_lat, min_lon: Southwest corner
            max_lat, max_lon: Northeast corner
            product: DEM product ('SRTM1' for 30m, 'SRTM3' for 90m, 'SRTM_BEST' for hybrid)
            progress_callback: Optional function(completed, total, message) to report progress

        Returns:
            Path to the downloaded/clipped DEM file (or tuple of paths for SRTM_BEST)
        """
        # Handle SRTM_BEST by downloading both and returning both paths
        if product == 'SRTM_BEST':
            print(f"  Using SRTM_BEST: downloading both SRTM1 and SRTM3")
            if progress_callback:
                progress_callback(0, 2, "Downloading SRTM1 elevation data (30m resolution)...")

            srtm1_file = None
            srtm3_file = None

            # Try SRTM1 first (may fail for some areas)
            try:
                srtm1_file = self._download_single_product(
                    min_lat, min_lon, max_lat, max_lon, 'SRTM1', progress_callback
                )
                print(f"  SRTM1 download successful")
            except Exception as e:
                print(f"  SRTM1 download failed (will use SRTM3 only): {e}")

            # Always download SRTM3 as fallback
            if progress_callback:
                progress_callback(1, 2, "Downloading SRTM3 elevation data (90m resolution)...")
            try:
                srtm3_file = self._download_single_product(
                    min_lat, min_lon, max_lat, max_lon, 'SRTM3', progress_callback
                )
                print(f"  SRTM3 download successful")
            except Exception as e:
                print(f"  ERROR: SRTM3 download failed: {e}")
                if srtm1_file:
                    print(f"  Using SRTM1 only")
                    return (srtm1_file, None)
                raise

            return (srtm1_file, srtm3_file)

        # Single product download
        if progress_callback:
            product_name = "SRTM1 (30m)" if product == 'SRTM1' else "SRTM3 (90m)"
            progress_callback(0, 1, f"Downloading {product_name} elevation data...")
        return self._download_single_product(min_lat, min_lon, max_lat, max_lon, product, progress_callback)

    def _download_single_product(self, min_lat, min_lon, max_lat, max_lon, product, progress_callback=None):
        """
        Download raw SRTM tiles for a bounding box and return VRT path.

        Downloads 1-degree SRTM tiles which are cached by the elevation library.
        Returns the VRT (Virtual Raster) path which acts as a mosaic of all tiles.
        No clipping or copying - just ensures raw tiles are cached.

        Args:
            min_lat, min_lon: Southwest corner
            max_lat, max_lon: Northeast corner
            product: DEM product ('SRTM1' or 'SRTM3')
            progress_callback: Optional function(completed, total, message) to report progress

        Returns:
            Path to the VRT file (virtual mosaic of raw tiles)
        """
        # Add small padding to ensure coverage
        padding = 0.01
        bounds = (min_lon - padding, min_lat - padding,
                 max_lon + padding, max_lat + padding)

        print(f"  Downloading DEM tiles for bounds: {bounds}")
        print(f"    Product: {product} ({'~30m' if product == 'SRTM1' else '~90m'} resolution)")

        import os
        cache_root = elevation.datasource.CACHE_DIR
        vrt_path = os.path.join(cache_root, product, f'{product}.vrt')

        # Check which tiles we need
        tiles_needed = self._get_tiles_for_bounds(bounds)
        tiles_missing = self._check_missing_tiles(tiles_needed, product, cache_root)

        if not tiles_missing:
            print(f"  All tiles already cached, using VRT: {vrt_path}")
            # Rebuild VRT to ensure it includes all tiles
            self._rebuild_vrt(cache_root, product)
            return vrt_path

        print(f"  Need to download {len(tiles_missing)} tiles")

        try:
            # Use elevation.clip to download tiles - the VRT is automatically created
            # We create a temporary output just to trigger the download
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.tif', delete=True) as tmp:
                elevation.clip(bounds=bounds, output=tmp.name, product=product)
            # File is automatically deleted, but tiles are now cached
            print(f"  Tiles downloaded, using VRT: {vrt_path}")
            return vrt_path

        except RuntimeError as e:
            if "Too many tiles" in str(e):
                # elevation library has a tile limit, so download in chunks
                print(f"  Too many tiles for single download, splitting into smaller chunks...")
                try:
                    self._download_tiles_in_chunks(bounds, product, progress_callback)
                    # Rebuild the VRT from cached tiles
                    elevation.clean()
                    print(f"  All tiles downloaded, using VRT: {vrt_path}")
                    return vrt_path
                except Exception as e2:
                    print(f"  ERROR downloading DEM tiles with chunked method: {e2}")
                    raise
            else:
                print(f"  ERROR downloading DEM tiles: {e}")
                raise
        except Exception as e:
            print(f"  ERROR downloading DEM tiles: {e}")
            raise

    def _download_tiles_in_chunks(self, bounds, product, progress_callback=None):
        """
        Download and process individual 1-degree tiles for a large area.

        Processes each 1-degree SRTM tile individually, matching the source data boundaries.
        This ensures we never reprocess a tile - once downloaded and processed, it's cached forever.

        Args:
            bounds: Tuple of (min_lon, min_lat, max_lon, max_lat)
            product: DEM product ('SRTM1' or 'SRTM3')
            progress_callback: Optional function(completed, total, message) to report progress
        """
        min_lon, min_lat, max_lon, max_lat = bounds

        # Get list of 1-degree tiles needed
        tiles_needed = self._get_tiles_for_bounds(bounds)
        tiles_missing = self._check_missing_tiles(tiles_needed, product, elevation.datasource.CACHE_DIR)

        total_tiles = len(tiles_missing)
        print(f"  Processing {total_tiles} tiles individually (1-degree tiles matching source data)...")

        # Process each 1-degree tile
        for idx, (lat, lon) in enumerate(tiles_missing):
            tile_num = idx + 1

            # 1-degree tile bounds (tile represents its SW corner)
            tile_bounds = (lon, lat, lon + 1, lat + 1)

            # Check if we have this tile processed already
            if self._is_chunk_cached(tile_bounds, product):
                print(f"  Tile {tile_num}/{total_tiles} already processed (lat={lat}, lon={lon})...")
                if progress_callback:
                    product_name = "SRTM1 (30m)" if product == 'SRTM1' else "SRTM3 (90m)"
                    progress_callback(tile_num - 1, total_tiles, f"Loading cached {product_name} tile ({tile_num}/{total_tiles})...")
                continue

            print(f"  Processing tile {tile_num}/{total_tiles} (lat={lat}, lon={lon})...")
            if progress_callback:
                product_name = "SRTM1 (30m)" if product == 'SRTM1' else "SRTM3 (90m)"
                progress_callback(tile_num - 1, total_tiles, f"Processing {product_name} tile ({tile_num}/{total_tiles})...")

            # Download and process this single 1-degree tile
            try:
                # Get cache path for this tile
                cache_path = self._get_chunk_cache_path(tile_bounds, product)
                os.makedirs(os.path.dirname(cache_path), exist_ok=True)

                # Run elevation.clip to download and process this single tile
                # Single 1-degree tile will never hit the "too many tiles" limit
                elevation.clip(bounds=tile_bounds, output=cache_path, product=product)
                print(f"  Tile {tile_num}/{total_tiles} processed and cached")

            except Exception as e:
                print(f"  ERROR processing tile (lat={lat}, lon={lon}): {e}")
                raise

        print(f"  All {total_tiles} tiles processed successfully")

    def _get_chunk_cache_path(self, bounds, product):
        """
        Get cache file path for a processed chunk.

        Args:
            bounds: Tuple of (min_lon, min_lat, max_lon, max_lat)
            product: DEM product ('SRTM1' or 'SRTM3')

        Returns:
            Path to cached chunk file
        """
        min_lon, min_lat, max_lon, max_lat = bounds

        # Create a stable filename based on bounds (aligned to degree boundaries)
        # Format: lon_lat_to_lon_lat.tif (e.g., -122_45_to_-120_47.tif)
        filename = f"{int(min_lon)}_{int(min_lat)}_to_{int(max_lon)}_{int(max_lat)}.tif"

        # Store in elevation cache under processed_chunks subdirectory
        cache_root = elevation.datasource.CACHE_DIR
        cache_dir = os.path.join(cache_root, product, 'processed_chunks')

        return os.path.join(cache_dir, filename)

    def _is_chunk_cached(self, bounds, product):
        """
        Check if a processed chunk is already cached.

        Args:
            bounds: Tuple of (min_lon, min_lat, max_lon, max_lat)
            product: DEM product ('SRTM1' or 'SRTM3')

        Returns:
            True if chunk is cached, False otherwise
        """
        cache_path = self._get_chunk_cache_path(bounds, product)
        return os.path.exists(cache_path)

    def _get_tiles_for_bounds(self, bounds):
        """
        Get list of 1-degree SRTM tiles needed for bounding box.

        Args:
            bounds: Tuple of (min_lon, min_lat, max_lon, max_lat)

        Returns:
            List of (lat, lon) tuples for tile southwest corners
        """
        min_lon, min_lat, max_lon, max_lat = bounds

        # SRTM tiles are 1-degree squares named by their SW corner
        tiles = []
        for lat in range(int(np.floor(min_lat)), int(np.ceil(max_lat))):
            for lon in range(int(np.floor(min_lon)), int(np.ceil(max_lon))):
                tiles.append((lat, lon))

        return tiles

    def _check_missing_tiles(self, tiles, product, cache_root):
        """
        Check which tiles are missing from the cache.

        Args:
            tiles: List of (lat, lon) tuples for tile southwest corners
            product: DEM product ('SRTM1' or 'SRTM3')
            cache_root: Cache directory root

        Returns:
            List of missing (lat, lon) tuples
        """
        import os
        import glob

        cache_dir = os.path.join(cache_root, product, 'cache')

        # SRTM1 and SRTM3 use different naming conventions
        if product == 'SRTM1':
            # SRTM1: Uses geographic names like N48W122.tif in subdirectories
            missing = []
            for lat, lon in tiles:
                lat_str = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
                lon_str = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
                tile_name = f"{lat_str}{lon_str}.tif"
                tile_path = os.path.join(cache_dir, lat_str, tile_name)

                if not os.path.exists(tile_path):
                    missing.append((lat, lon))
            return missing

        else:
            # SRTM3: Uses grid tile names like srtm_12_03.tif (flat structure)
            # We can't easily map lat/lon to SRTM3 tile grid coordinates,
            # so we just check if ANY tiles exist in the cache directory
            # If cache has tiles, assume coverage is complete for the area
            try:
                cached_tiles = glob.glob(os.path.join(cache_dir, 'srtm_*.tif'))
                if len(cached_tiles) > 0:
                    # Cache exists, assume it's complete
                    return []
                else:
                    # No cache, need to download
                    return tiles
            except Exception:
                # Can't check cache, assume need to download
                return tiles

    def _rebuild_vrt(self, cache_root, product):
        """
        Rebuild the VRT file from cached tiles.

        Args:
            cache_root: Cache directory root
            product: DEM product ('SRTM1' or 'SRTM3')
        """
        import os

        # Call elevation.clean() to rebuild VRT from all cached tiles
        # This is a no-op if tiles haven't changed, but ensures VRT is up to date
        try:
            elevation.clean()
        except Exception as e:
            print(f"  Warning: Could not rebuild VRT: {e}")

    def get_elevation(self, lat, lon, dem_file=None, dem_file_fallback=None):
        """
        Get elevation at a specific lat/lon coordinate.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            dem_file: Optional path to specific DEM file. If None, will try to
                     download tiles automatically for the point.
            dem_file_fallback: Optional fallback DEM file (for SRTM_BEST mode)

        Returns:
            Elevation in meters, or None if unavailable
        """
        # Track this query
        self.stats['total_queries'] += 1

        # Try primary DEM first
        elev = None
        used_fallback = False

        if dem_file is not None:
            elev = self._query_single_dem(lat, lon, dem_file)

        # If primary DEM returned NoData/None and we have a fallback, try it
        if (elev is None or elev == 0.0) and dem_file_fallback is not None:
            fallback_elev = self._query_single_dem(lat, lon, dem_file_fallback)
            if fallback_elev is not None and fallback_elev != 0.0:
                elev = fallback_elev
                used_fallback = True

        # Update statistics
        if dem_file_fallback is not None:  # Only track if in SRTM_BEST mode
            if used_fallback:
                self.stats['srtm3_fallback_queries'] += 1
            elif elev is not None and elev != 0.0:
                self.stats['srtm1_queries'] += 1

        return elev

    def _query_single_dem(self, lat, lon, dem_file):
        """
        Query a single DEM file for elevation.

        Args:
            lat: Latitude
            lon: Longitude
            dem_file: Path to DEM file

        Returns:
            Elevation in meters, 0.0 for NoData, or None if unavailable
        """
        try:
            # Convert to Path object if string
            dem_file = Path(dem_file)

            # Open raster (use cache to avoid repeated opens)
            if dem_file not in self._raster_cache:
                self._raster_cache[dem_file] = rasterio.open(dem_file)

            src = self._raster_cache[dem_file]

            # Sample elevation at the point
            # rasterio uses (x, y) = (lon, lat) order
            vals = list(src.sample([(lon, lat)]))

            if vals and len(vals) > 0:
                elev = float(vals[0][0])
                # Check for no-data values - return None to trigger fallback
                if src.nodata is not None and elev == src.nodata:
                    return None
                # SRTM uses -32768 as no-data in some cases
                if elev < -1000:
                    return None
                return elev

            return None

        except Exception as e:
            # Silently return None on error (expected for out-of-bounds queries)
            return None

    def get_elevations_batch(self, lat_lon_pairs, dem_file):
        """
        Get elevations for multiple points efficiently (batch query).

        Args:
            lat_lon_pairs: List of (lat, lon) tuples
            dem_file: Path to DEM file covering all points

        Returns:
            List of elevations (same order as input), None for unavailable points
        """
        try:
            dem_file = Path(dem_file)

            # Open raster
            if dem_file not in self._raster_cache:
                self._raster_cache[dem_file] = rasterio.open(dem_file)

            src = self._raster_cache[dem_file]

            # Convert to (lon, lat) order for rasterio
            coords = [(lon, lat) for lat, lon in lat_lon_pairs]

            # Batch sample
            elevations = []
            for val in src.sample(coords):
                elev = float(val[0])
                # Check for no-data
                if (src.nodata is not None and elev == src.nodata) or elev < -1000:
                    elevations.append(None)
                else:
                    elevations.append(elev)

            return elevations

        except Exception as e:
            print(f"Warning: Batch elevation query failed: {e}")
            return [None] * len(lat_lon_pairs)

    def cleanup(self):
        """Close all open raster datasets."""
        for src in self._raster_cache.values():
            src.close()
        self._raster_cache.clear()

    def __del__(self):
        """Cleanup on deletion."""
        self.cleanup()


def main():
    """Test/demo the DEM manager."""
    import argparse

    parser = argparse.ArgumentParser(description='Test DEM elevation queries')
    parser.add_argument('--lat', type=float, required=True, help='Latitude')
    parser.add_argument('--lon', type=float, required=True, help='Longitude')
    parser.add_argument('--bounds', nargs=4, type=float, metavar=('MIN_LAT', 'MIN_LON', 'MAX_LAT', 'MAX_LON'),
                       help='Download DEM for bounding box')
    parser.add_argument('--product', choices=['SRTM1', 'SRTM3'], default='SRTM3',
                       help='SRTM product (SRTM1=30m, SRTM3=90m)')

    args = parser.parse_args()

    dem = DEMManager()

    if args.bounds:
        # Download tiles for bounds
        min_lat, min_lon, max_lat, max_lon = args.bounds
        dem_file = dem.download_tiles_for_bounds(min_lat, min_lon, max_lat, max_lon,
                                                  product=args.product)
        print(f"\nDEM file: {dem_file}")

        # Query elevation at specified point
        elev = dem.get_elevation(args.lat, args.lon, dem_file)
    else:
        # Just query single point (will auto-download small area)
        elev = dem.get_elevation(args.lat, args.lon)

    if elev is not None:
        print(f"\nElevation at {args.lat}, {args.lon}: {elev:.1f}m")
    else:
        print(f"\nNo elevation data available at {args.lat}, {args.lon}")

    dem.cleanup()


if __name__ == '__main__':
    main()
