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

import elevation
import os
import rasterio
from rasterio.windows import from_bounds
import numpy as np
from pathlib import Path


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

        # Set elevation library cache directory
        os.environ['ELEVATION_CACHE_DIR'] = str(self.cache_dir)

        print(f"DEM cache directory: {self.cache_dir}")

    def download_tiles_for_bounds(self, min_lat, min_lon, max_lat, max_lon,
                                   product='SRTM3'):
        """
        Download DEM tiles covering a bounding box.

        Args:
            min_lat, min_lon: Southwest corner
            max_lat, max_lon: Northeast corner
            product: DEM product ('SRTM1' for 30m, 'SRTM3' for 90m)

        Returns:
            Path to the downloaded/clipped DEM file
        """
        # Add small padding to ensure coverage
        padding = 0.01
        bounds = (min_lon - padding, min_lat - padding,
                 max_lon + padding, max_lat + padding)

        output_file = self.cache_dir / f'dem_{min_lat}_{min_lon}_{max_lat}_{max_lon}.tif'

        # Check if already downloaded
        if output_file.exists():
            print(f"  Using cached DEM: {output_file.name}")
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
                # elevation library limits to 9 tiles, so we need to download using seed
                # which downloads tiles individually
                print(f"  Too many tiles for single download, using tile-by-tile method...")
                try:
                    # Seed downloads tiles one by one to the cache
                    elevation.seed(bounds=bounds, product=product, max_download_tiles=100)
                    # Now clip from the seeded cache
                    elevation.clip(bounds=bounds, output=str(output_file), product=product)
                    print(f"  Download complete: {output_file.name}")
                    return output_file
                except Exception as e2:
                    print(f"  ERROR downloading DEM tiles with seed method: {e2}")
                    raise
            else:
                print(f"  ERROR downloading DEM tiles: {e}")
                raise
        except Exception as e:
            print(f"  ERROR downloading DEM tiles: {e}")
            raise

    def get_elevation(self, lat, lon, dem_file=None):
        """
        Get elevation at a specific lat/lon coordinate.

        Args:
            lat: Latitude in decimal degrees
            lon: Longitude in decimal degrees
            dem_file: Optional path to specific DEM file. If None, will try to
                     download tiles automatically for the point.

        Returns:
            Elevation in meters, or None if unavailable
        """
        try:
            # If no DEM file specified, download a small area around the point
            if dem_file is None:
                # Download a 0.1 degree tile around the point
                dem_file = self.download_tiles_for_bounds(
                    lat - 0.05, lon - 0.05, lat + 0.05, lon + 0.05
                )

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
                # Check for no-data values
                if src.nodata is not None and elev == src.nodata:
                    return None
                # SRTM uses -32768 as no-data in some cases
                if elev < -1000:
                    return None
                return elev

            return None

        except Exception as e:
            print(f"Warning: Failed to get elevation for {lat},{lon}: {e}")
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
