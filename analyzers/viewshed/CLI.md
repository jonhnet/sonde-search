# Viewshed Analysis Tool

A tool for analyzing line-of-sight visibility from candidate antenna deployment locations for sonde receivers.

## Purpose

When planning where to deploy a sonde receiver antenna, it's critical to understand what area will be reachable by line-of-sight radio propagation. This tool computes and visualizes the "viewshed" - the geographic area visible from a given antenna location.

## Features

- **Line-of-sight analysis**: Calculates terrain obstruction accounting for Earth's curvature
- **Global coverage**: Uses SRTM elevation data available worldwide
- **Local DEM tiles**: Downloads and caches elevation data for fast, offline-capable analysis
- **Configurable parameters**: Adjust antenna height, analysis radius, and resolution
- **Visual output**: Generates maps showing visible (green) and blocked (grey) areas

## Installation

Install required dependencies:

```bash
pip install -r ../requirements.txt
```

Key dependencies:
- `rasterio` - Reading DEM raster files
- `elevation` - Downloading SRTM tiles
- `geographiclib` - Geodesic calculations
- `contextily` - Map basemaps

## Usage

### Basic Usage

Analyze a 10m antenna at a given location with 50km radius:

```bash
./viewshed.py --lat 47.6 --lon -122.3 --height 10 --radius 50
```

### Advanced Options

```bash
./viewshed.py \
  --lat 47.6062 \
  --lon -122.3321 \
  --height 20 \
  --radius 100 \
  --resolution 0.5 \
  --radials 72 \
  --dem-product SRTM1 \
  --output my-site-viewshed.png
```

### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--lat` | Latitude (decimal degrees) | Required |
| `--lon` | Longitude (decimal degrees) | Required |
| `--height` | Antenna height above ground (meters) | Required |
| `--radius` | Analysis radius (km) | 50 |
| `--resolution` | Radial spacing between test points (km) | 1.0 |
| `--radials` | Number of bearings to test (e.g., 36 = every 10°) | 36 |
| `--dem-product` | `SRTM1` (30m res) or `SRTM3` (90m res) | SRTM3 |
| `--use-api` | Use USGS API instead of local DEM (slower) | False |
| `--output` | Output filename | viewshed.png |

### Performance Tuning

**Quick preview** (faster, lower detail):
```bash
./viewshed.py --lat 47.6 --lon -122.3 --height 10 \
  --radius 30 --resolution 2 --radials 24
```

**High-resolution analysis** (slower, more accurate):
```bash
./viewshed.py --lat 47.6 --lon -122.3 --height 20 \
  --radius 100 --resolution 0.5 --radials 72 --dem-product SRTM1
```

## How It Works

1. **DEM Download**: Downloads SRTM elevation tiles covering the analysis area
2. **Grid Generation**: Creates a polar grid of test points around the antenna
3. **Visibility Testing**: For each point:
   - Samples terrain elevation along the ray from antenna to target
   - Accounts for Earth's curvature
   - Checks for terrain obstruction (with 10m Fresnel zone clearance)
4. **Visualization**: Plots results on an OpenStreetMap basemap

## Data Sources

### Elevation Data

**SRTM (Shuttle Radar Topography Mission)**
- **SRTM3**: ~90m resolution globally (except high latitudes)
- **SRTM1**: ~30m resolution for US and some other regions
- Automatically downloaded and cached in `~/.cache/srtm/`
- Source: NASA/USGS via `elevation` Python library

### Basemap

- OpenStreetMap Mapnik tiles
- Cached in `~/.cache/geotiles/`

## Output

The tool generates:

1. **PNG image** showing:
   - Green circles: Line-of-sight visible locations
   - Grey squares: Terrain-blocked locations
   - Red star: Antenna location
   - OpenStreetMap basemap

2. **Console summary**:
   - Observer elevation (MSL and AGL)
   - Visibility statistics
   - Maximum visible range

Example output:
```
======================================================================
SUMMARY
======================================================================
  Observer: 47.6062°, -122.3321°
  Ground elevation: 125.3m MSL
  Antenna height: 10.0m AGL
  Total antenna elevation: 135.3m MSL
  Visible points: 1584
  Blocked points: 216
  Visibility: 88.0%
  Maximum visible range: 49.5km
  Output saved to: viewshed.png
======================================================================
```

## Tips for Antenna Placement

1. **Higher is better**: Antenna height has dramatic impact on visibility
2. **Terrain matters**: Even 5-10m elevation difference can significantly change coverage
3. **Test multiple sites**: Run analysis for several candidate locations
4. **Consider practical constraints**: Also factor in power, network connectivity, access

## Comparison of Candidate Sites

To compare multiple antenna locations, run the tool for each:

```bash
# Site A
./viewshed.py --lat 47.60 --lon -122.30 --height 10 --output site_a.png

# Site B
./viewshed.py --lat 47.65 --lon -122.35 --height 10 --output site_b.png

# Site C (with taller tower)
./viewshed.py --lat 47.62 --lon -122.32 --height 20 --output site_c.png
```

Compare the maximum visible range and coverage patterns.

## Limitations

- **Terrain only**: Does not account for buildings, trees, or other obstructions
- **Fresnel clearance**: Uses simple 10m clearance; actual radio propagation is more complex
- **Resolution**: SRTM data is 30-90m resolution; fine details may be missed
- **No refraction**: Does not model atmospheric refraction (which can extend range)
- **VHF/UHF assumption**: Assumes line-of-sight propagation (appropriate for sonde frequencies)

## Technical Notes

### Earth Curvature

The tool accounts for Earth's curvature using:
```
h = d² / (2*R)
```
where d is distance and R is Earth's radius (6371 km).

### Line-of-Sight Testing

For each target point, samples 20 intermediate points along the ray and checks if terrain elevation exceeds the line-of-sight elevation at that distance.

### Coordinate Systems

- **Input/Output**: WGS84 (EPSG:4326) lat/lon
- **Visualization**: Web Mercator (EPSG:3857) for map rendering
- **Geodesics**: Uses accurate ellipsoidal Earth model via `geographiclib`

## DEM Manager Module

The `dem_manager.py` module provides standalone DEM tile management:

```python
from dem_manager import DEMManager

dem = DEMManager(cache_dir='~/.cache/srtm')

# Download tiles for a bounding box
dem_file = dem.download_tiles_for_bounds(
    min_lat=47.5, min_lon=-122.5,
    max_lat=47.7, max_lon=-122.1,
    product='SRTM3'
)

# Query elevation at a point
elevation = dem.get_elevation(47.6, -122.3, dem_file)
print(f"Elevation: {elevation}m")

dem.cleanup()
```

## Troubleshooting

**Error: "Could not determine observer elevation"**
- Ensure lat/lon are valid and have SRTM coverage
- Try using `--use-api` flag to use USGS API instead

**Slow performance**
- Use `--resolution 2` for faster preview
- Reduce `--radials` to 24 or 18
- First run downloads DEM tiles; subsequent runs are much faster

**Out of memory**
- Reduce `--radius` or increase `--resolution`
- Use SRTM3 instead of SRTM1

## Related Tools

- `coverage.py` - Plots actual received sonde coverage from log files
- `landings-heatmap.py` - Maps historical sonde landing locations

## References

- [SRTM Data](https://www2.jpl.nasa.gov/srtm/)
- [Radio Propagation Basics](https://en.wikipedia.org/wiki/Line-of-sight_propagation)
- [Viewshed Analysis](https://en.wikipedia.org/wiki/Viewshed)
