"""Unit tests for lib/landing_calendar.py"""

import io
import os
import sys
import tempfile
from unittest import mock

import pandas as pd
from PIL import Image
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _make_test_dataframe():
    """Create a test DataFrame mimicking sonde summary data with landings
    spread across multiple months and locations."""
    records = []
    for month in range(1, 13):
        for i in range(3):
            records.append({
                'serial': f'SONDE-M{month}-{i}',
                'frame': 100 + i,
                'lat': 47.0 + i * 0.1,
                'lon': -122.0 - i * 0.1,
                'datetime': f'2023-{month:02d}-15',
            })
    return pd.DataFrame(records)


# Patch contextily.add_basemap globally for all tests — avoids tile downloads
@pytest.fixture(autouse=True)
def no_basemap():
    with mock.patch('lib.landing_calendar.cx.add_basemap'):
        yield


@pytest.fixture(autouse=True)
def mock_sonde_data():
    with mock.patch(
        'lib.landing_calendar.get_sonde_summaries_as_dataframe',
        return_value=_make_test_dataframe(),
    ):
        yield


class TestGenerateCalendar:
    def test_returns_png_bytes(self):
        from lib.landing_calendar import generate_calendar

        result = generate_calendar(46, -123, 48, -121, format='png')

        img = Image.open(io.BytesIO(result))
        assert img.format == 'PNG'

    def test_returns_webp_bytes(self):
        from lib.landing_calendar import generate_calendar

        result = generate_calendar(46, -123, 48, -121, format='webp')

        img = Image.open(io.BytesIO(result))
        assert img.format == 'WEBP'

    def test_grid_dimensions(self):
        """The output image should be a 3-wide x 4-tall grid of month images."""
        from lib.landing_calendar import generate_calendar

        result = generate_calendar(46, -123, 48, -121, format='png')

        img = Image.open(io.BytesIO(result))
        # Grid is 3 columns x 4 rows, so width should be ~3x height/4
        # (approximately square cells means width/height ≈ 3/4)
        aspect = img.width / img.height
        assert 0.4 < aspect < 1.0, f"Unexpected aspect ratio {aspect}"

    def test_no_data_in_bounds_still_produces_image(self):
        """Bounds with no landings should still produce a valid image
        (12 empty maps)."""
        from lib.landing_calendar import generate_calendar

        # Bounds far from any test data
        result = generate_calendar(0, 0, 1, 1, format='png')

        img = Image.open(io.BytesIO(result))
        assert img.format == 'PNG'
        assert img.width > 0 and img.height > 0


class TestGenerateCalendarToFile:
    def test_writes_file(self):
        from lib.landing_calendar import generate_calendar_to_file

        with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as f:
            path = f.name

        try:
            generate_calendar_to_file(46, -123, 48, -121, path, format='webp')

            assert os.path.exists(path)
            assert os.path.getsize(path) > 0

            img = Image.open(path)
            assert img.format == 'WEBP'
        finally:
            os.unlink(path)


class TestRenderOneMonth:
    def test_returns_pil_image(self):
        from lib.landing_calendar import _render_one_month, _filter_and_project

        df = _make_test_dataframe()
        df['datetime'] = pd.to_datetime(df['datetime'])
        df['month'] = df['datetime'].dt.month
        gdf = _filter_and_project(df, 46, -123, 48, -121)

        month_data = gdf.loc[gdf.month == 1]
        img = _render_one_month(month_data, 'January', gdf.crs)

        assert isinstance(img, Image.Image)
        assert img.width > 0 and img.height > 0

    def test_empty_month_returns_image(self):
        from lib.landing_calendar import _render_one_month, _filter_and_project

        df = _make_test_dataframe()
        df['datetime'] = pd.to_datetime(df['datetime'])
        df['month'] = df['datetime'].dt.month
        gdf = _filter_and_project(df, 0, 0, 1, 1)  # No data here

        img = _render_one_month(gdf, 'January', gdf.crs)

        assert isinstance(img, Image.Image)


class TestCompositeGrid:
    def test_grid_layout(self):
        from lib.landing_calendar import _composite_grid, CALENDAR_ROWS, CALENDAR_COLS

        cell_size = 100
        images = [Image.new('RGB', (cell_size, cell_size), 'red') for _ in range(12)]

        result_bytes = _composite_grid(images, 'png')

        result = Image.open(io.BytesIO(result_bytes))
        assert result.width == cell_size * CALENDAR_COLS
        assert result.height == cell_size * CALENDAR_ROWS

    def test_varying_cell_sizes(self):
        """When individual images differ in size, the grid should use the
        max dimensions and center smaller images."""
        from lib.landing_calendar import _composite_grid, CALENDAR_ROWS, CALENDAR_COLS

        images = []
        for i in range(12):
            # Alternate between two sizes
            size = 100 if i % 2 == 0 else 80
            images.append(Image.new('RGB', (size, size), 'blue'))

        result_bytes = _composite_grid(images, 'png')

        result = Image.open(io.BytesIO(result_bytes))
        assert result.width == 100 * CALENDAR_COLS
        assert result.height == 100 * CALENDAR_ROWS


class TestFilterAndProject:
    def test_filters_to_bounds(self):
        from lib.landing_calendar import _filter_and_project

        df = _make_test_dataframe()
        df['datetime'] = pd.to_datetime(df['datetime'])

        gdf = _filter_and_project(df, 46.5, -122.5, 47.15, -121.5)

        # Some points should match, but not all
        assert len(gdf) > 0
        assert len(gdf) < len(df)

    def test_empty_result(self):
        from lib.landing_calendar import _filter_and_project

        df = _make_test_dataframe()
        df['datetime'] = pd.to_datetime(df['datetime'])

        gdf = _filter_and_project(df, 0, 0, 1, 1)

        assert len(gdf) == 0

    def test_output_is_web_mercator(self):
        from lib.landing_calendar import _filter_and_project

        df = _make_test_dataframe()
        df['datetime'] = pd.to_datetime(df['datetime'])

        gdf = _filter_and_project(df, 46, -123, 48, -121)

        assert gdf.crs.to_epsg() == 3857
