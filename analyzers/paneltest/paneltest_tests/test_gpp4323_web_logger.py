#!/usr/bin/env python3
"""
Unit tests for GPP4323 web logger
"""

import pytest
import tempfile
import os
from datetime import datetime, timezone
import pandas as pd
from gpp4323_web_logger import DataStore, decimate_data
from gpp4323_lib import LoadReading


def test_decimate_data_no_decimation():
    """Test that decimation with window_size=1 returns original data"""
    df = pd.DataFrame({
        'elapsed': [1.0, 2.0, 3.0],
        'voltage': [5.0, 5.1, 5.2],
        'current': [1.0, 1.1, 1.2],
        'power': [5.0, 5.61, 6.24],
        'energy_wh': [0.001, 0.003, 0.005]
    })

    result = decimate_data(df, window_size=1)
    pd.testing.assert_frame_equal(result, df)


def test_decimate_data_complete_windows():
    """Test decimation with complete windows"""
    df = pd.DataFrame({
        'elapsed': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        'voltage': [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
        'current': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        'power': [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
        'energy_wh': [0.001, 0.003, 0.006, 0.010, 0.015, 0.021]
    })

    result = decimate_data(df, window_size=2)

    assert len(result) == 3
    assert result['elapsed'].iloc[0] == pytest.approx(1.5)  # Mean of 1.0, 2.0
    assert result['current'].iloc[0] == pytest.approx(1.5)  # Mean of 1.0, 2.0
    assert result['power'].iloc[0] == pytest.approx(7.5)    # Mean of 5.0, 10.0
    assert result['energy_wh'].iloc[0] == pytest.approx(0.003)  # Last of window


def test_decimate_data_incomplete_window():
    """Test that incomplete windows are discarded"""
    df = pd.DataFrame({
        'elapsed': [1.0, 2.0, 3.0, 4.0, 5.0],
        'voltage': [5.0, 5.0, 5.0, 5.0, 5.0],
        'current': [1.0, 2.0, 3.0, 4.0, 5.0],
        'power': [5.0, 10.0, 15.0, 20.0, 25.0],
        'energy_wh': [0.001, 0.003, 0.006, 0.010, 0.015]
    })

    result = decimate_data(df, window_size=2)

    # Should have 2 complete windows (4 points), discarding the 5th point
    assert len(result) == 2
    assert result['elapsed'].iloc[1] == pytest.approx(3.5)  # Mean of 3.0, 4.0


def test_decimate_data_too_small():
    """Test that data smaller than window_size is returned unchanged"""
    df = pd.DataFrame({
        'elapsed': [1.0, 2.0],
        'voltage': [5.0, 5.0],
        'current': [1.0, 2.0],
        'power': [5.0, 10.0],
        'energy_wh': [0.001, 0.003]
    })

    result = decimate_data(df, window_size=3)
    pd.testing.assert_frame_equal(result, df)


def test_energy_integration():
    """Test that energy is correctly integrated from power readings"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name

    try:
        store = DataStore(logfile_path=logfile)
        store.open_log_file()

        # Create readings 1 second apart with constant 10W power
        for i in range(5):
            reading = LoadReading(
                voltage=5.0,
                current=2.0,
                power=10.0,
                timestamp=datetime(2025, 1, 1, 0, 0, i, tzinfo=timezone.utc)
            )
            store.handle_reading(reading)

        # After 4 seconds at 10W, should have accumulated:
        # 10W * 4s / 3600 = 0.011111... Wh
        assert store.total_energy_wh == pytest.approx(10.0 * 4 / 3600, rel=1e-5)

        # Check that data was written to memory
        assert len(store.data) == 5
        assert store.data['power'].iloc[0] == 10.0

        store.close_log_file()
    finally:
        os.unlink(logfile)


def test_get_latest_empty():
    """Test get_latest returns None when no data"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name

    try:
        store = DataStore(logfile_path=logfile)
        latest = store.get_latest()
        assert latest is None
    finally:
        os.unlink(logfile)


def test_get_latest_with_data():
    """Test get_latest returns a Series with correct data"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name

    try:
        store = DataStore(logfile_path=logfile)
        store.open_log_file()

        reading = LoadReading(
            voltage=5.0,
            current=2.0,
            power=10.0,
            timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        )
        store.handle_reading(reading)

        latest = store.get_latest()
        assert latest is not None
        assert latest['voltage'] == 5.0
        assert latest['current'] == 2.0
        assert latest['power'] == 10.0
        assert latest['elapsed'] == 0.0

        store.close_log_file()
    finally:
        os.unlink(logfile)


def test_unix_epoch_timestamp_format():
    """Test that CSV uses Unix epoch timestamp format"""
    # Create a temp file but delete it so store can create a fresh one
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=True) as f:
        logfile = f.name

    try:
        store = DataStore(logfile_path=logfile)
        store.open_log_file()

        reading = LoadReading(
            voltage=5.0,
            current=2.0,
            power=10.0,
            timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        )
        store.handle_reading(reading)
        store.close_log_file()

        # Read the CSV and check timestamp format
        with open(logfile, 'r') as f:
            lines = f.readlines()
            # Should have header + 1 data row
            assert len(lines) == 2
            # Check that first column is a float (Unix epoch)
            data_row = lines[1].split(',')
            timestamp = float(data_row[0])
            # Should be around Jan 1, 2025 (Unix epoch ~1735689600)
            assert timestamp >= 1735689600
            assert timestamp < 1735690000  # Within ~6 minutes
    finally:
        if os.path.exists(logfile):
            os.unlink(logfile)


def test_load_historical_data():
    """Test loading historical data from CSV"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name
        # Write some test data
        f.write('timestamp,elapsed,voltage,current,power,energy_wh\n')
        f.write('1735689600.000,0.000,5.0000,2.0000,10.0000,0.000000\n')
        f.write('1735689601.000,1.000,5.0000,2.0000,10.0000,0.002778\n')
        f.write('1735689602.000,2.000,5.0000,2.0000,10.0000,0.005556\n')

    try:
        store = DataStore(logfile_path=logfile)
        store.load_historical_data()

        # Check that data was loaded
        assert len(store.data) == 3
        assert store.total_sample_count == 3
        assert store.total_energy_wh == pytest.approx(0.005556)
        assert store.start_timestamp is not None

        # Check that timestamp column was dropped from in-memory data
        assert 'timestamp' not in store.data.columns
        assert 'elapsed' in store.data.columns
    finally:
        os.unlink(logfile)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
