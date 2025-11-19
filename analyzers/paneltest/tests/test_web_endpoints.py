#!/usr/bin/env python3
"""
Integration tests for GPP4323 web endpoints
"""

import pytest
import tempfile
import os
from datetime import datetime, timezone
from gpp4323_web_logger import DataStore, WebServer
from gpp4323_lib import LoadReading


@pytest.fixture
def data_store():
    """Create a temporary data store for testing"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name

    store = DataStore(logfile_path=logfile)
    store.open_log_file()

    # Add some test data
    for i in range(10):
        reading = LoadReading(
            voltage=5.0,
            current=2.0,
            power=10.0,
            timestamp=datetime(2025, 1, 1, 0, 0, i, tzinfo=timezone.utc)
        )
        store.handle_reading(reading)

    yield store

    store.close_log_file()
    os.unlink(logfile)


@pytest.fixture
def web_server(data_store):
    """Create a web server with test data"""
    return WebServer(data_store)


@pytest.fixture
def client(web_server):
    """Create a Flask test client"""
    web_server.app.config['TESTING'] = True
    return web_server.app.test_client()


def test_index_route(client):
    """Test that the index route returns the HTML page"""
    response = client.get('/')
    assert response.status_code == 200
    assert b'GPP4323 Power Monitor' in response.data


def test_stats_stream(data_store):
    """Test that stats stream generator works correctly"""
    # Test the data store directly (which is what stream_stats uses)
    latest = data_store.get_latest()

    # This was the bug - ensure we use 'is not None'
    assert latest is not None

    # Verify we can access fields with dictionary syntax
    assert latest['elapsed'] >= 0
    assert latest['voltage'] == 5.0
    assert latest['current'] == 2.0
    assert latest['power'] == 10.0

    # Verify get_total_sample_count works
    assert data_store.get_total_sample_count() == 10


def test_get_new_data(data_store):
    """Test get_new_data returns correct filtered data"""
    # Get all data after time -1 (before first point at 0.0)
    new_data = data_store.get_new_data(-1.0)

    # Should have all 10 data points (0.0 through 9.0)
    assert len(new_data) == 10

    # Get data after time 5.0 (strictly greater than)
    new_data = data_store.get_new_data(5.0)

    # Should have 4 points (6.0, 7.0, 8.0, 9.0 elapsed seconds)
    assert len(new_data) == 4
    assert new_data.iloc[0]['elapsed'] > 5.0
    assert new_data.iloc[0]['elapsed'] == 6.0




def test_get_latest_with_series(data_store):
    """Test that get_latest returns a Series that can be checked with 'is not None'"""
    latest = data_store.get_latest()

    # This is the pattern that was causing the bug
    # We should use 'is not None', not just 'if latest:'
    assert latest is not None

    # Accessing with dictionary-style indexing should work
    assert latest['voltage'] == 5.0
    assert latest['current'] == 2.0
    assert latest['power'] == 10.0


def test_empty_data_store():
    """Test that empty data store handles get_latest gracefully"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        logfile = f.name

    try:
        store = DataStore(logfile_path=logfile)
        store.open_log_file()

        # get_latest should return None for empty store
        latest = store.get_latest()
        assert latest is None

        # This is the pattern that should be used (not 'if latest:')
        if latest is not None:
            # Should not execute
            assert False, "Should not reach here with empty store"

        store.close_log_file()
    finally:
        os.unlink(logfile)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
