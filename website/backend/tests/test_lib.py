import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from lib.map_utils import get_elevation, identify_ground_points
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
