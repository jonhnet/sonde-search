import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

import numpy as np
import pandas as pd

import lib.map_utils as map_utils
from lib.map_utils import MapUtils, get_elevation, identify_ground_points
from website.backend.src.util import FakeSondeHub, SondeHubRetrieverBase


class Test_Elevation:
    """Tests for the elevation API with worldwide coverage."""

    @pytest.mark.parametrize(
        "lat,lon,expect_elevation,description",
        [
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
        ],
    )
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
        sh = FakeSondeHub("V1221460-singlesonde")
        flight_df, _ = sh.get_sonde_data(params={"serial": "V1221460"})

        # Get ground points
        ground_points = identify_ground_points(flight_df)

        # Should have found some ground points
        assert ground_points is not None, "Expected ground points but got None"
        assert len(ground_points) > 0, "Expected at least one ground point"

        # Every ground point should have vel_v and vel_h < 1 m/s
        assert (
            ground_points["vel_v"].abs() < 1
        ).all(), f"Found ground points with |vel_v| >= 1: {ground_points[ground_points['vel_v'].abs() >= 1]}"
        assert (
            ground_points["vel_h"].abs() < 1
        ).all(), f"Found ground points with |vel_h| >= 1: {ground_points[ground_points['vel_h'].abs() >= 1]}"

    @staticmethod
    def _flight(velocities):
        """Build a minimal flight DataFrame from a list of (vel_v, vel_h) tuples."""
        return pd.DataFrame(
            {
                "frame": range(len(velocities)),
                "alt": [200.0] * len(velocities),
                "lat": [47.5] * len(velocities),
                "lon": [-122.3] * len(velocities),
                "vel_v": [v[0] for v in velocities],
                "vel_h": [v[1] for v in velocities],
            }
        )

    def test_nan_velocity_counted_as_ground_not_truncating_run(self):
        """NaN velocities (synthetic velocity not computed for a frame) must count
        as zero, not chop the trailing ground run. A grounded sonde with NaN
        frames sprinkled through its on-ground period yields the whole run."""
        nan = float("nan")
        # 1 airborne frame, then 6 on-ground frames, two of which have NaN velocity.
        flight = self._flight(
            [(5.0, 8.0), (0.1, 0.2), (nan, 0.1), (0.0, 0.3), (0.2, nan), (0.1, 0.1), (0.0, 0.2)]
        )
        ground = identify_ground_points(flight)
        assert ground is not None
        # All 6 trailing frames are on the ground, NaN ones included.
        assert len(ground) == 6, f"NaN frames wrongly excluded from run: got {len(ground)}"

    def test_trailing_nan_velocity_still_detects_ground(self):
        """If the very last received frame has NaN velocity, the sonde must still
        be recognized as grounded (this was the 503-2-02485 bug: the block and
        map were suppressed because the last frame's NaN read looked airborne)."""
        nan = float("nan")
        flight = self._flight([(5.0, 8.0), (0.1, 0.2), (0.0, 0.1), (nan, nan)])
        ground = identify_ground_points(flight)
        assert ground is not None, "Trailing NaN-velocity frame wrongly suppressed ground detection"
        assert len(ground) == 3

    def test_all_nan_velocity_is_not_ground_reception(self):
        """A data error where velocity is entirely NaN must NOT be read as a long
        ground reception (zero-filling alone would make the whole flight 'ground')."""
        nan = float("nan")
        flight = self._flight([(nan, nan), (nan, nan), (nan, nan)])
        assert identify_ground_points(flight) is None

    def test_airborne_with_trailing_nan_is_not_ground(self):
        """A still-airborne sonde whose only ground-looking frame is a trailing NaN
        must not be reported as grounded -- the run has no measured velocity."""
        nan = float("nan")
        flight = self._flight([(5.0, 8.0), (6.0, 7.0), (nan, nan)])
        assert identify_ground_points(flight) is None

    def test_absent_velocity_columns_is_not_ground_reception(self):
        """A sonde that never reports velocity has no vel_v/vel_h columns at all.

        That must degrade to "cannot confirm ground reception" rather than
        raising KeyError. The crash cost affected subscribers their whole
        notification: process_one_sub() catches per subscriber, so the sonde was
        silently dropped for them (seen in production as
        "Error notifying <user>: 'vel_v'").
        """
        flight = self._flight([(0.1, 0.2), (0.0, 0.1)]).drop(columns=["vel_v", "vel_h"])
        assert identify_ground_points(flight) is None

    def test_one_absent_velocity_column_is_not_ground_reception(self):
        """Half the velocity data is still not a confirmed measurement."""
        for missing in ("vel_v", "vel_h"):
            flight = self._flight([(0.1, 0.2), (0.0, 0.1)]).drop(columns=[missing])
            assert identify_ground_points(flight) is None, f"missing {missing} not handled"

    def test_absent_velocity_columns_on_airborne_sonde(self):
        """The absent-column path must not depend on the trace looking grounded."""
        flight = self._flight([(5.0, 8.0), (6.0, 7.0)]).drop(columns=["vel_v", "vel_h"])
        assert identify_ground_points(flight) is None


class Test_GetMapLimits:
    """Tests for map boundary/zoom calculation, including degenerate inputs."""

    def setup_method(self):
        self.mu = MapUtils()

    @pytest.mark.parametrize(
        "points,description",
        [
            ([(47.5, -122.3)], "single point"),
            ([(47.5, -122.3), (47.5, -122.3), (47.5, -122.3)], "identical points"),
            ([(47.5, -122.3), (47.5, -121.9)], "same latitude, different longitude"),
            ([(47.5, -122.3), (47.9, -122.3)], "same longitude, different latitude"),
        ],
    )
    def test_degenerate_extents(self, points, description):
        """Degenerate point sets must not divide by zero and must yield sane bounds."""
        min_x, min_y, max_x, max_y, zoom = self.mu.get_map_limits(points)

        assert min_x < max_x, f"Empty x-extent for {description}"
        assert min_y < max_y, f"Empty y-extent for {description}"
        assert all(
            np.isfinite(v) for v in (min_x, min_y, max_x, max_y)
        ), f"Non-finite bounds for {description}"
        assert isinstance(zoom, int), f"Zoom not an int for {description}"
        assert 1 <= zoom <= 18, f"Zoom {zoom} out of range for {description}"

    def test_normal_extent(self):
        """A well-spread set of points should still produce sane bounds and zoom."""
        points = [(47.0, -123.0), (48.0, -121.0)]
        min_x, min_y, max_x, max_y, zoom = self.mu.get_map_limits(points)

        assert min_x < max_x and min_y < max_y
        assert 1 <= zoom <= 18

    def test_min_span_zero_keeps_tiny_extent(self):
        """min_span=0 must not inflate a few-meters-wide cluster to the default floor.

        The ground reception map relies on this: its points span only meters, and
        the default ~1 km floor would zoom it uselessly far out.
        """
        # Two points ~3 m apart in latitude.
        points = [(47.5, -122.3), (47.5 + 3e-5, -122.3)]

        floored = self.mu.get_map_limits(points)
        tight = self.mu.get_map_limits(points, map_whitespace=0, min_span=0)

        # The default floor blows the extent up; min_span=0 keeps it tight.
        assert (floored[2] - floored[0]) > (tight[2] - tight[0])
        assert (tight[2] - tight[0]) < 100, "few-meters cluster should stay under 100 m wide"
        assert tight[4] == 18, "a meters-wide map should be at max zoom"

    def test_min_span_zero_single_point(self):
        """min_span=0 with a single point must not divide by zero; zoom caps at 18."""
        min_x, min_y, max_x, max_y, zoom = self.mu.get_map_limits(
            [(47.5, -122.3)], map_whitespace=0, min_span=0
        )

        assert all(np.isfinite(v) for v in (min_x, min_y, max_x, max_y))
        assert zoom == 18


class Test_AddBasemap:
    """Tests for the basemap helper's tolerance of tile-download failures."""

    def test_success_first_try(self, monkeypatch):
        calls = []
        monkeypatch.setattr(map_utils.cx, "add_basemap", lambda *a, **k: calls.append(1))
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


class Test_SondeHubDatetimeParsing:
    """Regression tests for mixed-precision timestamps in SondeHub telemetry.

    On 2026-08-20 a new uploader (SondeFox 0.12.1) began emitting ISO8601
    timestamps without fractional seconds. Every other uploader includes them.
    pandas infers a datetime format from the first element and applies it
    strictly to the rest, so a single such record raised ValueError inside
    cleanup_sonde_data(). That call sits outside the retry loop in
    get_sonde_data() and outside the per-subscriber try/except in
    process_all_subs(), so one bad record out of 4046 killed every hourly
    notifier run before a single subscriber was processed.
    """

    # Fractional-seconds record must come first: that is what pandas infers
    # the format from, and what makes the non-fractional one fail.
    WITH_SUBSECONDS = "2026-08-20T10:29:59.005000Z"
    NO_SUBSECONDS = "2026-08-20T12:21:59Z"

    def _telemetry(self, datetimes):
        """Build a minimal telemetry frame in the shape cleanup_sonde_data expects."""
        return pd.DataFrame(
            [
                {
                    "serial": f"S{i}",
                    "datetime": dt,
                    "alt": "1000.5",  # SondeHub sometimes sends these as strings
                    "lat": "47.5",
                    "lon": "-122.3",
                    "vel_v": "-5.0",
                    "vel_h": "3.0",
                }
                for i, dt in enumerate(datetimes)
            ]
        )

    def test_mixed_subsecond_precision_does_not_raise(self):
        """The exact production failure: one non-fractional record among many."""
        sondes = self._telemetry([self.WITH_SUBSECONDS] * 5 + [self.NO_SUBSECONDS])

        cleaned = SondeHubRetrieverBase().cleanup_sonde_data(sondes)

        assert len(cleaned) == 6
        assert cleaned["datetime"].notna().all()
        assert cleaned["datetime"].iloc[-1] == pd.Timestamp("2026-08-20 12:21:59", tz="UTC")
        # Downstream code sorts and compares these, so they must be a real
        # datetime column rather than object-dtype Timestamps.
        assert str(cleaned["datetime"].dtype).endswith("UTC]")

    def test_uniform_precision_still_works(self):
        """Neither uniform spelling may regress."""
        for stamp in (self.WITH_SUBSECONDS, self.NO_SUBSECONDS):
            cleaned = SondeHubRetrieverBase().cleanup_sonde_data(self._telemetry([stamp] * 3))
            assert cleaned["datetime"].notna().all()
            assert cleaned["alt"].dtype == float

    def test_missing_velocity_columns_tolerated(self):
        """vel_v/vel_h are optional; their absence must not break parsing."""
        sondes = self._telemetry([self.WITH_SUBSECONDS, self.NO_SUBSECONDS]).drop(
            columns=["vel_v", "vel_h"]
        )

        cleaned = SondeHubRetrieverBase().cleanup_sonde_data(sondes)

        assert cleaned["datetime"].notna().all()
