# Viewshed Analysis Service

A web-based tool for computing and visualizing line-of-sight viewsheds for antenna placement planning.

## What is this?

This service calculates which areas are visible from a given location (e.g., an antenna site) based on terrain data. It's useful for:

- **Sonde receiver placement**: Determine optimal locations for radiosonde tracking stations
- **Radio coverage planning**: Estimate radio line-of-sight coverage
- **Site surveys**: Evaluate potential antenna locations before field deployment

## Features

- **Interactive web interface** with OpenStreetMap/OpenTopoMap integration
- **Click-to-select** antenna locations on the map
- **Real-time visualization** of visible (green) and blocked (red) areas
- **Configurable parameters**: radius, grid density, antenna height
- **DEM tile caching** for fast repeated computations
- **Terrain-aware basemap** using OpenTopoMap
- **State persistence** remembers your last location and settings

## Quick Start

### Local Development

```bash
# From the viewshed directory
cd /path/to/sonde-search/analyzers/viewshed

# Install dependencies (first time only)
pip install -r ../requirements.txt
sudo apt install gdal-bin  # For DEM processing

# Run the server
python viewshed_server.py

# Open browser
http://localhost:6565
```

### Docker/Podman Deployment

```bash
# Build and run
docker-compose up -d

# Or with Podman
podman-compose up -d
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed production deployment instructions.

## How It Works

1. **Select Location**: Click the map or enter coordinates
2. **Configure Parameters**:
   - Antenna height (meters above ground)
   - Analysis radius (km)
   - Grid resolution (number of test points)
   - DEM product (SRTM1=30m or SRTM3=90m resolution)
3. **Compute**: The service:
   - Downloads SRTM elevation tiles (cached locally)
   - Tests line-of-sight to each grid point
   - Accounts for Earth curvature
   - Applies Fresnel zone clearance (10m margin)
4. **Visualize**: Results overlay on the map with:
   - Green circles = visible areas
   - Red circles = terrain-blocked areas

## Files

- **`viewshed_server.py`** - CherryPy web service with Leaflet.js frontend
- **`viewshed.py`** - Core viewshed computation logic (CLI tool + library)
- **`dem_manager.py`** - SRTM DEM tile download and management
- **`Dockerfile`** - Container image definition
- **`docker-compose.yml`** - Docker/Podman orchestration
- **`nginx-example.conf`** - Nginx reverse proxy configuration
- **`DEPLOYMENT.md`** - Production deployment guide
- **`README_WEBSERVICE.md`** - Detailed API documentation

## Architecture

```
┌─────────────────────────────────────────┐
│  Browser (Leaflet.js + OpenTopoMap)     │
│  - Interactive map                      │
│  - Click to set antenna location        │
│  - Real-time result visualization       │
└──────────────────┬──────────────────────┘
                   │ HTTP/JSON
┌──────────────────┴──────────────────────┐
│  CherryPy Web Server (viewshed_server)  │
│  - REST API endpoints                   │
│  - Background job processing            │
│  - GeoJSON generation                   │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────┴──────────────────────┐
│  Viewshed Engine (viewshed.py)          │
│  - Line-of-sight calculation            │
│  - Earth curvature correction           │
│  - Fresnel zone clearance               │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────┴──────────────────────┐
│  DEM Manager (dem_manager.py)           │
│  - SRTM tile download (elevation lib)   │
│  - Tile caching (~/.cache/srtm)         │
│  - Elevation queries (rasterio)         │
└─────────────────────────────────────────┘
```

## API

### POST `/compute`
Start a viewshed computation.

**Request:**
```json
{
  "lat": 47.6062,
  "lon": -122.3321,
  "height": 10,
  "radius": 50,
  "grid_points": 25,
  "dem_product": "SRTM3"
}
```

**Response:**
```json
{
  "job_id": "abc123..."
}
```

### GET `/status/<job_id>`
Poll job status.

**Response (completed):**
```json
{
  "status": "completed",
  "observer_elevation": 125.3,
  "visible_count": 584,
  "blocked_count": 41,
  "visibility_pct": 93.4,
  "max_range_km": 49.2
}
```

### GET `/geojson/<job_id>`
Get viewshed results as GeoJSON.

See [README_WEBSERVICE.md](README_WEBSERVICE.md) for complete API documentation.

## Configuration

Edit `viewshed_server.py` to customize:

```python
PORT = 6565              # Server port
HOST = '0.0.0.0'         # Listen address
```

## Performance

- **First run**: Downloads DEM tiles (~30-60 seconds for new area)
- **Subsequent runs**: Uses cached tiles (much faster)
- **Grid size**: 25x25 = 625 points takes ~5-15 seconds
- **Large radius**: 150km radius may require many tiles (use SRTM3)

## Limitations

- **Job persistence**: Jobs lost on server restart (in-memory storage)
- **Concurrency**: One computation per CPU core
- **SRTM coverage**: Global coverage, but resolution varies
- **Water bodies**: Treated as sea level (0m elevation)

## Requirements

Python packages:
- cherrypy
- numpy
- matplotlib
- rasterio
- elevation (for SRTM download)
- geographiclib

System packages:
- gdal-bin
- libgdal-dev

## Credits

- **SRTM Data**: NASA Shuttle Radar Topography Mission
- **OpenTopoMap**: Terrain-focused basemap
- **Leaflet.js**: Interactive mapping library
- **elevation library**: Easy SRTM tile management

## License

Part of the sonde-search project.
