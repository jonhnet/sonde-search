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
                                   product='SRTM3'):
        """
        Download DEM tiles covering a bounding box.

        Args:
            min_lat, min_lon: Southwest corner
            max_lat, max_lon: Northeast corner
            product: DEM product ('SRTM1' for 30m, 'SRTM3' for 90m, 'SRTM_BEST' for hybrid)

        Returns:
            Path to the downloaded/clipped DEM file (or tuple of paths for SRTM_BEST)
        """
        # Handle SRTM_BEST by downloading both and returning both paths
        if product == 'SRTM_BEST':
            print(f"  Using SRTM_BEST: downloading both SRTM1 and SRTM3")
            srtm1_file = None
            srtm3_file = None

            # Try SRTM1 first (may fail for some areas)
            try:
                srtm1_file = self._download_single_product(
                    min_lat, min_lon, max_lat, max_lon, 'SRTM1'
                )
                print(f"  SRTM1 download successful")
            except Exception as e:
                print(f"  SRTM1 download failed (will use SRTM3 only): {e}")

            # Always download SRTM3 as fallback
            try:
                srtm3_file = self._download_single_product(
                    min_lat, min_lon, max_lat, max_lon, 'SRTM3'
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
        return self._download_single_product(min_lat, min_lon, max_lat, max_lon, product)

    def _download_single_product(self, min_lat, min_lon, max_lat, max_lon, product):
        """
        Download a single DEM product for a bounding box.

        Args:
            min_lat, min_lon: Southwest corner
            max_lat, max_lon: Northeast corner
            product: DEM product ('SRTM1' or 'SRTM3')

        Returns:
            Path to the downloaded/clipped DEM file
        """
        # Add small padding to ensure coverage
        padding = 0.01
        bounds = (min_lon - padding, min_lat - padding,
                 max_lon + padding, max_lat + padding)

        output_file = self.cache_dir / f'dem_{product}_{min_lat}_{min_lon}_{max_lat}_{max_lon}.tif'

        # Check if already downloaded
        if output_file.exists():
            print(f"  Using cached {product} DEM: {output_file.name}")
            return output_file

        print(f"  Downloading DEM tiles for bounds: {bounds}")
        print(f"    Product: {product} ({'~30m' if product == 'SRTM1' else '~90m'} resolution)")

        try:
            # Download and clip to bounds
            elevation.clip(bounds=bounds, output=str(output_file), product=product)
            print(f"  Download complete: {output_file.name}")
            return output_file

        except RuntimeError as e:
            if "Too many tiles" in str(e):
                # elevation library has a tile limit, so we need to split the area
                # into smaller chunks and download them separately
                print(f"  Too many tiles for single download, splitting into smaller chunks...")
                try:
                    # Split the bounding box into smaller chunks
                    # We'll use a 3x3 grid of sub-boxes to stay well under the limit
                    self._download_tiles_in_chunks(bounds, product)

                    # Now we need to clip from the cache without trying to seed again
                    # Call elevation.clean() to rebuild the VRT from cached tiles
                    elevation.clean()

                    # Now clip with max_download_tiles=0 to prevent any new downloads
                    # This forces it to use only what's in the cache
                    import subprocess
                    import os

                    # Get the cache directory for this product
                    # The elevation library uses a different cache structure
                    import os
                    cache_root = os.path.expanduser('~/.cache/elevation')
                    vrt_path = os.path.join(cache_root, product, f'{product}.vrt')

                    # Use gdal_translate directly to clip from the VRT
                    min_lon, min_lat, max_lon, max_lat = bounds
                    cmd = [
                        'gdal_translate',
                        '-co', 'TILED=YES',
                        '-co', 'COMPRESS=DEFLATE',
                        '-co', 'ZLEVEL=9',
                        '-co', 'PREDICTOR=2',
                        '-projwin', str(min_lon), str(max_lat), str(max_lon), str(min_lat),
                        vrt_path,
                        str(output_file)
                    ]
                    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    if result.stderr:
                        print(f"  gdal_translate stderr: {result.stderr}")

                    print(f"  Download complete: {output_file.name}")
                    return output_file
                except Exception as e2:
                    print(f"  ERROR downloading DEM tiles with chunked method: {e2}")
                    raise
            else:
                print(f"  ERROR downloading DEM tiles: {e}")
                raise
        except Exception as e:
            print(f"  ERROR downloading DEM tiles: {e}")
            raise

    def _download_tiles_in_chunks(self, bounds, product):
        """
        Download tiles for a large area by splitting into smaller chunks.

        Args:
            bounds: Tuple of (min_lon, min_lat, max_lon, max_lat)
            product: DEM product ('SRTM1' or 'SRTM3')
        """
        min_lon, min_lat, max_lon, max_lat = bounds

        # Calculate chunk size - split into a grid that keeps each chunk small
        # SRTM tiles are 1 degree squares, and the limit is around 20 tiles
        # So we'll aim for chunks of about 2x2 degrees (4 tiles max)
        chunk_size = 2.0  # degrees

        # Calculate number of chunks needed in each direction
        lon_range = max_lon - min_lon
        lat_range = max_lat - min_lat

        num_lon_chunks = int(np.ceil(lon_range / chunk_size))
        num_lat_chunks = int(np.ceil(lat_range / chunk_size))

        total_chunks = num_lon_chunks * num_lat_chunks
        print(f"  Splitting into {num_lon_chunks}x{num_lat_chunks} = {total_chunks} chunks...")

        # Download each chunk
        chunk_num = 0
        for i in range(num_lon_chunks):
            for j in range(num_lat_chunks):
                chunk_num += 1

                # Calculate chunk bounds
                chunk_min_lon = min_lon + i * chunk_size
                chunk_max_lon = min(chunk_min_lon + chunk_size, max_lon)
                chunk_min_lat = min_lat + j * chunk_size
                chunk_max_lat = min(chunk_min_lat + chunk_size, max_lat)

                chunk_bounds = (chunk_min_lon, chunk_min_lat, chunk_max_lon, chunk_max_lat)

                print(f"  Downloading chunk {chunk_num}/{total_chunks}...")

                # Try to download this chunk
                try:
                    # Use a temporary file for the chunk
                    chunk_file = self.cache_dir / f'temp_chunk_{i}_{j}.tif'
                    elevation.clip(bounds=chunk_bounds, output=str(chunk_file), product=product)
                    # Remove the temporary file - we just needed to populate the cache
                    if chunk_file.exists():
                        chunk_file.unlink()
                except RuntimeError as e:
                    if "Too many tiles" in str(e):
                        # Even the chunk is too big - recursively split it
                        print(f"  Chunk still too large, splitting further...")
                        self._download_tiles_in_chunks(chunk_bounds, product)
                    else:
                        raise

        print(f"  All {total_chunks} chunks downloaded successfully")

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
