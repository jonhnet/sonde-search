"""
Shared utilities for generating maps of sonde flights and landing locations.
"""

from typing import Tuple
import numpy as np
import requests
from pyproj import Transformer


# Whitespace padding around map boundaries (20%)
MAP_WHITESPACE = 0.2


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


# Get ground elevation at a given lat/lon using USGS elevation API
def get_elevation(lat, lon):
    resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
        'x': lon,
        'y': lat,
        'units': 'Meters',
        'wkid': '4326',
        'includeDate': 'True',
    })
    resp.raise_for_status()
    return float(resp.json()['value'])
