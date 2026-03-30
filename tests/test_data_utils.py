"""Unit tests for lib/data_utils.py"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.data_utils import filter_real_flights, get_landing_rows, MIN_MAX_ALT, MIN_ALT_DROP


def _make_sonde(serial, max_alt, final_alt):
    """Helper to create a two-frame sonde: one at peak, one at final altitude."""
    return [
        {'serial': serial, 'frame': 100, 'alt': max_alt},
        {'serial': serial, 'frame': 200, 'alt': final_alt},
    ]


def test_real_flight_passes():
    """A sonde that reached high altitude and descended should pass."""
    df = pd.DataFrame(_make_sonde('GOOD', 20000, 500))
    result = filter_real_flights(df)
    assert len(result) == 2


def test_ground_test_rejected():
    """A sonde that never reached MIN_MAX_ALT should be filtered out."""
    df = pd.DataFrame(_make_sonde('GROUND', 100, 50))
    result = filter_real_flights(df)
    assert len(result) == 0


def test_still_ascending_rejected():
    """A sonde still near its peak altitude should be filtered out."""
    df = pd.DataFrame(_make_sonde('ASCENDING', 15000, 14800))
    result = filter_real_flights(df)
    assert len(result) == 0


def test_mixed_sondes():
    """Only real flights should survive from a mix of valid and invalid sondes."""
    records = (
        _make_sonde('GOOD1', 20000, 500) +
        _make_sonde('GROUND', 100, 50) +
        _make_sonde('GOOD2', 10000, 2000) +
        _make_sonde('ASCENDING', 15000, 14800)
    )
    df = pd.DataFrame(records)
    result = filter_real_flights(df)
    serials = set(result['serial'])
    assert serials == {'GOOD1', 'GOOD2'}


def test_borderline_altitude():
    """A sonde at exactly MIN_MAX_ALT with exactly MIN_ALT_DROP should pass."""
    df = pd.DataFrame(_make_sonde('BORDER', MIN_MAX_ALT, MIN_MAX_ALT - MIN_ALT_DROP))
    result = filter_real_flights(df)
    assert len(result) == 2


def test_just_below_thresholds():
    """A sonde just below the altitude threshold should be rejected."""
    df = pd.DataFrame(_make_sonde('LOW', MIN_MAX_ALT - 1, 0))
    result = filter_real_flights(df)
    assert len(result) == 0


def test_insufficient_drop():
    """A sonde above MIN_MAX_ALT but with less than MIN_ALT_DROP descent should be rejected."""
    df = pd.DataFrame(_make_sonde('NODROP', 10000, 10000 - MIN_ALT_DROP + 1))
    result = filter_real_flights(df)
    assert len(result) == 0


def test_empty_dataframe():
    """An empty DataFrame should return empty."""
    df = pd.DataFrame(columns=['serial', 'frame', 'alt'])
    result = filter_real_flights(df)
    assert len(result) == 0


# --- get_landing_rows tests ---

def test_get_landing_rows_picks_last_frame():
    """Should return the row with the highest frame number for each sonde."""
    df = pd.DataFrame([
        {'serial': 'A', 'frame': 100, 'lat': 1.0},
        {'serial': 'A', 'frame': 200, 'lat': 2.0},
        {'serial': 'A', 'frame': 300, 'lat': 3.0},
        {'serial': 'B', 'frame': 50, 'lat': 10.0},
        {'serial': 'B', 'frame': 150, 'lat': 20.0},
    ])
    result = get_landing_rows(df)
    assert len(result) == 2
    assert result.loc[result['serial'] == 'A', 'frame'].iloc[0] == 300
    assert result.loc[result['serial'] == 'B', 'frame'].iloc[0] == 150


def test_get_landing_rows_single_frame():
    """A sonde with only one frame should still be returned."""
    df = pd.DataFrame([
        {'serial': 'SOLO', 'frame': 42, 'lat': 5.0},
    ])
    result = get_landing_rows(df)
    assert len(result) == 1
    assert result.iloc[0]['frame'] == 42


def test_get_landing_rows_empty():
    """An empty DataFrame should return empty."""
    df = pd.DataFrame(columns=['serial', 'frame'])
    result = get_landing_rows(df)
    assert len(result) == 0
