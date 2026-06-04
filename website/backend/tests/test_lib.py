import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import numpy as np

import lib.map_utils as map_utils
from lib.map_utils import MapUtils, get_elevation, identify_ground_points
from website.backend.src.util import FakeSondeHub


class Test_Elevation:
    """Tests for the elevation API with worldwide coverage."""

    @pytest.mark.parametrize("lat,lon,expect_elevation,description", [
        (47.97916, -123.72867, True, "Olympic National Park, WA"),
        (53.95138, -4.71504, True, "Snowdonia, Wales"),
        (46.8182, 8.2275, True, "Swiss Alps"),
        (50.1787, 4.70067, True, "Belgium"),
        (48.70669, 6.94685, True, "France"),
        (30.64842, -82.49796, True, "Florida"),
        (45.4215, -75.6972, True, "Ottawa, Canada"),
        (40.02813, -103.24538, True, "Colorado"),
        (64.8378, -147.7164, True, "Fairbanks, Alaska"),
        (41.33726, -70.04312, True, "Nantucket, MA"),
        (60.55457, 24.87695, True, "Finland"),
        (30.81391, -80.75313, False, "Atlantic Ocean off Florida"),
    ])
    def test_elevation_worldwide(self, lat, lon, expect_elevation, description):
        """Test elevation lookup returns expected results for locations worldwide."""
        elev = get_elevation(lat, lon)
        if expect_elevation:
            assert elev is not None, f"Elevation returned None for {description}"
            assert isinstance(elev, float), f"Elevation not a float for {description}"
        else:
            assert elev is None, f"Expected None for {description}, got {elev}"


class Test_GroundPoints:
    """Tests for ground point identification."""

    def test_identify_ground_points_V1221460(self):
        """Test that identify_ground_points returns only points with vel_v and vel_h < 1."""
        # Load test data
        sh = FakeSondeHub('V1221460-singlesonde')
        flight_df, _ = sh.get_sonde_data(params={'serial': 'V1221460'})

        # Get ground points
        ground_points = identify_ground_points(flight_df)

        # Should have found some ground points
        assert ground_points is not None, "Expected ground points but got None"
        assert len(ground_points) > 0, "Expected at least one ground point"

        # Every ground point should have vel_v and vel_h < 1 m/s
        assert (ground_points['vel_v'].abs() < 1).all(), \
            f"Found ground points with |vel_v| >= 1: {ground_points[ground_points['vel_v'].abs() >= 1]}"
        assert (ground_points['vel_h'].abs() < 1).all(), \
            f"Found ground points with |vel_h| >= 1: {ground_points[ground_points['vel_h'].abs() >= 1]}"


class Test_GetMapLimits:
    """Tests for map boundary/zoom calculation, including degenerate inputs."""

    def setup_method(self):
        self.mu = MapUtils()

    @pytest.mark.parametrize("points,description", [
        ([(47.5, -122.3)], "single point"),
        ([(47.5, -122.3), (47.5, -122.3), (47.5, -122.3)], "identical points"),
        ([(47.5, -122.3), (47.5, -121.9)], "same latitude, different longitude"),
        ([(47.5, -122.3), (47.9, -122.3)], "same longitude, different latitude"),
    ])
    def test_degenerate_extents(self, points, description):
        """Degenerate point sets must not divide by zero and must yield sane bounds."""
        min_x, min_y, max_x, max_y, zoom = self.mu.get_map_limits(points)

        assert min_x < max_x, f"Empty x-extent for {description}"
        assert min_y < max_y, f"Empty y-extent for {description}"
        assert all(np.isfinite(v) for v in (min_x, min_y, max_x, max_y)), \
            f"Non-finite bounds for {description}"
        assert isinstance(zoom, int), f"Zoom not an int for {description}"
        assert 1 <= zoom <= 18, f"Zoom {zoom} out of range for {description}"

    def test_normal_extent(self):
        """A well-spread set of points should still produce sane bounds and zoom."""
        points = [(47.0, -123.0), (48.0, -121.0)]
        min_x, min_y, max_x, max_y, zoom = self.mu.get_map_limits(points)

        assert min_x < max_x and min_y < max_y
        assert 1 <= zoom <= 18


class Test_AddBasemap:
    """Tests for the basemap helper's tolerance of tile-download failures."""

    def test_success_first_try(self, monkeypatch):
        calls = []
        monkeypatch.setattr(map_utils.cx, "add_basemap",
                            lambda *a, **k: calls.append(1))
        assert map_utils.add_basemap(ax=None, zoom=10) is True
        assert len(calls) == 1

    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr(map_utils.time, "sleep", lambda s: None)
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) < 3:
                raise TypeError("int() argument must be ..., not 'NoneType'")

        monkeypatch.setattr(map_utils.cx, "add_basemap", flaky)
        assert map_utils.add_basemap(ax=None, zoom=10, attempts=3) is True
        assert len(calls) == 3

    def test_gives_up_without_raising(self, monkeypatch):
        monkeypatch.setattr(map_utils.time, "sleep", lambda s: None)
        calls = []

        def always_fails(*a, **k):
            calls.append(1)
            raise TypeError("int() argument must be ..., not 'NoneType'")

        monkeypatch.setattr(map_utils.cx, "add_basemap", always_fails)
        # Must not raise -- a tile failure should not abort the whole run.
        assert map_utils.add_basemap(ax=None, zoom=10, attempts=3) is False
        assert len(calls) == 3
