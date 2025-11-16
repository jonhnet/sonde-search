"""Unit tests for analyzers/kml_generator.py CLI tool"""

import sys
import os
from unittest import mock
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_kml_generator_cli_success():
    """Test that the CLI successfully generates KML file"""
    mock_kml_content = '<?xml version="1.0" encoding="UTF-8"?><kml>test</kml>'

    with mock.patch('lib.kml_generator.generate_kml', return_value=mock_kml_content):
        with mock.patch('builtins.open', mock.mock_open()) as mock_file:
            from analyzers.kml_generator import main

            with mock.patch('sys.argv', ['kml_generator.py', 'V1854526']):
                main()

            # Verify the file was opened and written
            mock_file.assert_called_once_with('V1854526.kml', 'w')
            mock_file().write.assert_called_once_with(mock_kml_content)


def test_kml_generator_cli_custom_output():
    """Test that the CLI respects custom output filename"""
    mock_kml_content = '<?xml version="1.0" encoding="UTF-8"?><kml>test</kml>'

    with mock.patch('lib.kml_generator.generate_kml', return_value=mock_kml_content):
        with mock.patch('builtins.open', mock.mock_open()) as mock_file:
            from analyzers.kml_generator import main

            with mock.patch('sys.argv', ['kml_generator.py', 'V1854526', '-o', 'custom.kml']):
                main()

            # Verify custom filename was used
            mock_file.assert_called_once_with('custom.kml', 'w')
            mock_file().write.assert_called_once_with(mock_kml_content)


def test_kml_generator_cli_not_found():
    """Test that the CLI exits with error when sonde not found"""
    with mock.patch('lib.kml_generator.generate_kml',
                    side_effect=ValueError("Sonde NONEXISTENT does not exist or has no data")):
        from analyzers.kml_generator import main

        with mock.patch('sys.argv', ['kml_generator.py', 'NONEXISTENT']):
            with pytest.raises(SystemExit) as exc_info:
                main()

            # Verify it exited with the error message
            assert "does not exist" in str(exc_info.value)
