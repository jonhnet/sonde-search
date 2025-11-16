"""Unit tests for analyzers/listeners.py CLI tool"""

import sys
import os
from unittest import mock
import pytest
from io import StringIO

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_listeners_cli_success():
    """Test that the CLI successfully displays listener data"""
    # Mock data that would be returned from get_listener_stats
    import pandas as pd

    mock_stats = pd.DataFrame({
        ('frame', 'first'): [100, 200],
        ('frame', 'last'): [500, 600],
        ('frame', 'count'): [401, 401],
        ('cov%',): [100.0, 100.0],
        ('time', 'first'): ['10:00:00Z', '10:05:00Z'],
        ('time', 'last'): ['11:00:00Z', '11:05:00Z'],
        ('alt', 'first'): [1000, 1000],
        ('alt', 'last'): [10000, 10000],
        ('vel_v', 'first'): [5.0, 5.0],
        ('vel_v', 'last'): [-10.0, -10.0],
    }, index=['LISTENER1', 'LISTENER2'])
    mock_stats.index.name = 'uploader_callsign'

    mock_coverage = pd.Series({
        'LISTENER1,LISTENER2': 300,
        'LISTENER1': 100,
        'LISTENER2': 100,
    })

    mock_result = {
        'stats': mock_stats,
        'coverage': mock_coverage,
        'warning': None
    }

    with mock.patch('lib.listeners.get_listener_stats', return_value=mock_result):
        # Capture stdout
        captured_output = StringIO()
        sys.stdout = captured_output

        # Import and run the main function
        from analyzers.listeners import main

        with mock.patch('sys.argv', ['listeners.py', 'TESTSONDE']):
            main()

        # Restore stdout
        sys.stdout = sys.__stdout__

        output = captured_output.getvalue()

        # Verify output contains expected data
        assert 'LISTENER1' in output
        assert 'LISTENER2' in output
        assert 'Number of points heard by:' in output


def test_listeners_cli_with_warning():
    """Test that the CLI displays warnings"""
    import pandas as pd

    mock_stats = pd.DataFrame({
        ('frame', 'first'): [100],
        ('frame', 'last'): [500],
        ('frame', 'count'): [401],
        ('cov%',): [100.0],
        ('time', 'first'): ['10:00:00Z'],
        ('time', 'last'): ['11:00:00Z'],
        ('alt', 'first'): [1000],
        ('alt', 'last'): [10000],
        ('vel_v', 'first'): [5.0],
        ('vel_v', 'last'): [-10.0],
    }, index=['LISTENER1'])
    mock_stats.index.name = 'uploader_callsign'

    mock_coverage = pd.Series({'LISTENER1': 401})

    mock_result = {
        'stats': mock_stats,
        'coverage': mock_coverage,
        'warning': 'Using live data API that only returns one listener per data point'
    }

    with mock.patch('lib.listeners.get_listener_stats', return_value=mock_result):
        captured_output = StringIO()
        sys.stdout = captured_output

        from analyzers.listeners import main

        with mock.patch('sys.argv', ['listeners.py', 'TESTSONDE']):
            main()

        sys.stdout = sys.__stdout__
        output = captured_output.getvalue()

        # Verify warning is displayed
        assert 'Warning:' in output
        assert 'live data API' in output


def test_listeners_cli_not_found():
    """Test that the CLI exits with error when sonde not found"""
    with mock.patch('lib.listeners.get_listener_stats',
                    side_effect=ValueError("Cannot find sonde 'NONEXISTENT'")):
        from analyzers.listeners import main

        with mock.patch('sys.argv', ['listeners.py', 'NONEXISTENT']):
            with pytest.raises(SystemExit) as exc_info:
                main()

            # Verify it exited with the error message
            assert "Cannot find sonde" in str(exc_info.value)
