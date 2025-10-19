#!/usr/bin/env python3

"""
CherryPy-based web service for viewshed analysis.

Provides a web interface to compute and visualize antenna viewsheds.

Usage:
    ./viewshed_server.py

Then visit: http://localhost:6565
"""

import cherrypy
import io
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
import sys
import threading
import time
import uuid
from pathlib import Path

# Import viewshed computation modules
sys.path.insert(0, os.path.dirname(__file__))
from viewshed import compute_viewshed, plot_viewshed
from dem_manager import DEMManager

# Configuration
PORT = 6565
HOST = '0.0.0.0'
OUTPUT_DIR = Path('/tmp/viewshed_outputs')
OUTPUT_DIR.mkdir(exist_ok=True)

# Job storage (in-memory for now)
jobs = {}
jobs_lock = threading.Lock()


class ViewshedServer:
    """CherryPy web service for viewshed analysis."""

    @cherrypy.expose
    def index(self):
        """Serve the main HTML interface."""
        return """
<!DOCTYPE html>
<html>
<head>
    <title>Viewshed Analysis - Sonde Receiver Antenna Planning</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            padding: 0;
            margin: 0;
            overflow: hidden;
        }

        .container {
            max-width: 100%;
            height: 100vh;
            margin: 0;
            display: flex;
            flex-direction: row;
        }

        .sidebar {
            width: 400px;
            background: white;
            box-shadow: 2px 0 4px rgba(0,0,0,0.1);
            padding: 30px;
            overflow-y: auto;
            z-index: 1000;
        }

        .map-container {
            flex: 1;
            position: relative;
        }

        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }

        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }

        .form-group {
            display: flex;
            flex-direction: column;
        }

        label {
            font-weight: 600;
            margin-bottom: 5px;
            color: #333;
            font-size: 14px;
        }

        .label-help {
            font-weight: normal;
            color: #666;
            font-size: 12px;
            margin-top: 2px;
        }

        input, select {
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }

        input:focus, select:focus {
            outline: none;
            border-color: #4CAF50;
        }

        button {
            background: #4CAF50;
            color: white;
            border: none;
            padding: 12px 30px;
            border-radius: 4px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
        }

        button:hover {
            background: #45a049;
        }

        button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        #status {
            margin-top: 20px;
            padding: 15px;
            border-radius: 4px;
            display: none;
        }

        #status.info {
            background: #e3f2fd;
            border: 1px solid #2196F3;
            color: #1976D2;
            display: block;
        }

        #status.success {
            background: #e8f5e9;
            border: 1px solid #4CAF50;
            color: #2e7d32;
            display: block;
        }

        #status.error {
            background: #ffebee;
            border: 1px solid #f44336;
            color: #c62828;
            display: block;
        }

        #map {
            width: 100%;
            height: 100%;
            z-index: 0;
        }

        .leaflet-container {
            height: 100%;
            width: 100%;
        }

        #results-panel {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
        }

        #results-panel.hidden {
            display: none;
        }

        .result-stats {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            margin-top: 15px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .stat-item {
            text-align: center;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: #4CAF50;
        }

        .stat-label {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            margin-top: 5px;
        }

        .presets {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .preset-btn {
            padding: 8px 16px;
            background: #e0e0e0;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
            transition: background 0.3s;
        }

        .preset-btn:hover {
            background: #d0d0d0;
        }

        .advanced {
            margin-top: 20px;
            border-top: 1px solid #e0e0e0;
            padding-top: 20px;
        }

        .section-title {
            font-weight: 600;
            color: #333;
            margin-bottom: 15px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <h1>Viewshed Analysis</h1>
            <p class="subtitle">Antenna Line-of-Sight Planning for Sonde Receivers</p>

            <div style="background: #e3f2fd; border: 1px solid #2196F3; color: #1976D2; padding: 10px; border-radius: 4px; margin-bottom: 20px; font-size: 13px;">
                <b>💡 Tip:</b> Click anywhere on the map to set the antenna location
            </div>

            <div class="presets">
            <button class="preset-btn" onclick="loadPreset('quick')">Quick Preview</button>
            <button class="preset-btn" onclick="loadPreset('standard')">Standard</button>
            <button class="preset-btn" onclick="loadPreset('detailed')">High Detail</button>
        </div>

        <form id="viewshedForm" onsubmit="submitForm(event)">
            <div class="form-grid">
                <div class="form-group">
                    <label>
                        Latitude
                        <div class="label-help">Decimal degrees (-90 to 90)</div>
                    </label>
                    <input type="number" id="lat" step="0.0001" min="-90" max="90" value="47.6062" required>
                </div>

                <div class="form-group">
                    <label>
                        Longitude
                        <div class="label-help">Decimal degrees (-180 to 180)</div>
                    </label>
                    <input type="number" id="lon" step="0.0001" min="-180" max="180" value="-122.3321" required>
                </div>

                <div class="form-group">
                    <label>
                        Antenna Height
                        <div class="label-help">Meters above ground</div>
                    </label>
                    <input type="number" id="height" step="0.1" min="1" value="10" required>
                </div>

                <div class="form-group">
                    <label>
                        Analysis Radius
                        <div class="label-help">Kilometers</div>
                    </label>
                    <input type="number" id="radius" step="1" min="1" max="200" value="50" required>
                </div>
            </div>

            <div class="advanced">
                <div class="section-title">Advanced Options</div>
                <div class="form-grid">
                    <div class="form-group">
                        <label>
                            Grid Size
                            <div class="label-help">Points per side (NxN grid)</div>
                        </label>
                        <input type="number" id="grid_points" step="1" min="10" max="200" value="25">
                    </div>

                    <div class="form-group">
                        <label>
                            DEM Product
                            <div class="label-help">Elevation data resolution</div>
                        </label>
                        <select id="dem_product">
                            <option value="SRTM3">SRTM3 (90m, faster)</option>
                            <option value="SRTM1">SRTM1 (30m, better)</option>
                        </select>
                    </div>
                </div>
            </div>

            <button type="submit" id="submitBtn">Compute Viewshed</button>
        </form>

            <div id="status"></div>

            <div id="results-panel" class="hidden">
                <h3>Results</h3>
                <div class="result-stats" id="stats"></div>
            </div>
        </div>

        <div class="map-container">
            <div id="map"></div>
        </div>
    </div>

    <script>
        let pollInterval = null;
        let map = null;
        let viewshedLayer = null;

        let selectedMarker = null;

        // Load saved state from localStorage
        function loadSavedState() {
            const saved = localStorage.getItem('viewshed_state');
            if (saved) {
                try {
                    return JSON.parse(saved);
                } catch (e) {
                    return null;
                }
            }
            return null;
        }

        // Save state to localStorage
        function saveState() {
            const center = map.getCenter();
            const zoom = map.getZoom();
            const state = {
                lat: parseFloat(document.getElementById('lat').value),
                lon: parseFloat(document.getElementById('lon').value),
                mapCenter: { lat: center.lat, lng: center.lng },
                mapZoom: zoom
            };
            localStorage.setItem('viewshed_state', JSON.stringify(state));
        }

        // Create or update the antenna marker
        function setAntennaMarker(lat, lon) {
            const latlng = L.latLng(lat, lon);

            if (selectedMarker) {
                selectedMarker.setLatLng(latlng);
            } else {
                selectedMarker = L.marker(latlng, {
                    draggable: true,
                    icon: L.icon({
                        iconUrl: 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48Y2lyY2xlIGN4PSIxMiIgY3k9IjEyIiByPSI4IiBmaWxsPSIjZmYwMDAwIiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iMiIvPjwvc3ZnPg==',
                        iconSize: [24, 24],
                        iconAnchor: [12, 12]
                    })
                }).addTo(map);

                selectedMarker.bindPopup('<b>Proposed Antenna Location</b><br>Click "Compute Viewshed" to analyze');

                // Handle marker drag
                selectedMarker.on('dragend', function(e) {
                    const pos = e.target.getLatLng();
                    document.getElementById('lat').value = pos.lat.toFixed(4);
                    document.getElementById('lon').value = pos.lng.toFixed(4);
                    saveState();
                });
            }
        }

        // Initialize map on page load
        document.addEventListener('DOMContentLoaded', function() {
            // Load saved state or use defaults
            const savedState = loadSavedState();
            let initialLat, initialLon, initialZoom;

            if (savedState) {
                initialLat = savedState.mapCenter.lat;
                initialLon = savedState.mapCenter.lng;
                initialZoom = savedState.mapZoom;

                // Update form fields with saved antenna location
                document.getElementById('lat').value = savedState.lat.toFixed(4);
                document.getElementById('lon').value = savedState.lon.toFixed(4);
            } else {
                // Use defaults from form
                initialLat = parseFloat(document.getElementById('lat').value);
                initialLon = parseFloat(document.getElementById('lon').value);
                initialZoom = 8;
            }

            map = L.map('map').setView([initialLat, initialLon], initialZoom);

            // Use OpenTopoMap for terrain emphasis
            L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: 'Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)',
                maxZoom: 17
            }).addTo(map);

            // Draw initial antenna marker from form values
            const antennaLat = parseFloat(document.getElementById('lat').value);
            const antennaLon = parseFloat(document.getElementById('lon').value);
            setAntennaMarker(antennaLat, antennaLon);

            // Save state when map moves
            map.on('moveend', saveState);
            map.on('zoomend', saveState);

            // Add click handler to set antenna location
            map.on('click', function(e) {
                const lat = e.latlng.lat;
                const lon = e.latlng.lng;

                // Update form fields
                document.getElementById('lat').value = lat.toFixed(4);
                document.getElementById('lon').value = lon.toFixed(4);

                // Update marker
                setAntennaMarker(lat, lon);
                selectedMarker.openPopup();

                // Save state
                saveState();
            });

            // Save state when form fields change
            document.getElementById('lat').addEventListener('change', saveState);
            document.getElementById('lon').addEventListener('change', saveState);
        });

        function loadPreset(preset) {
            const presets = {
                quick: {
                    radius: 30,
                    grid_points: 15,
                    dem_product: 'SRTM3'
                },
                standard: {
                    radius: 50,
                    grid_points: 25,
                    dem_product: 'SRTM3'
                },
                detailed: {
                    radius: 100,
                    grid_points: 50,
                    dem_product: 'SRTM1'
                }
            };

            const p = presets[preset];
            document.getElementById('radius').value = p.radius;
            document.getElementById('grid_points').value = p.grid_points;
            document.getElementById('dem_product').value = p.dem_product;
        }

        function showStatus(message, type) {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = type;
        }

        function hideStatus() {
            document.getElementById('status').style.display = 'none';
        }

        function loadViewshedData(jobId) {
            // Fetch GeoJSON data and display on map
            fetch(`/geojson/${jobId}`)
                .then(r => r.json())
                .then(geojson => {
                    // Get grid spacing from GeoJSON metadata
                    const gridSpacing = geojson.properties?.grid_spacing_meters || 5000;
                    // Use half the grid spacing as radius so circles touch
                    const radius = gridSpacing / 2;
                    console.log('Grid spacing (m):', gridSpacing, 'Circle radius (m):', radius);

                    viewshedLayer = L.geoJSON(geojson, {
                        pointToLayer: function(feature, latlng) {
                            if (feature.properties.type === 'observer') {
                                // Observer location - red circle marker (pixel-based, doesn't scale)
                                return L.circleMarker(latlng, {
                                    radius: 10,
                                    fillColor: '#ff0000',
                                    color: '#000',
                                    weight: 2,
                                    opacity: 1,
                                    fillOpacity: 0.8
                                }).bindPopup(
                                    `<b>Antenna Location</b><br>` +
                                    `Height: ${feature.properties.height_agl.toFixed(1)}m AGL<br>` +
                                    `Elevation: ${feature.properties.elevation_msl.toFixed(1)}m MSL`
                                );
                            } else if (feature.properties.visible) {
                                // Visible points - green circles (meter-based, scales with zoom)
                                return L.circle(latlng, {
                                    radius: radius,
                                    fillColor: '#00ff00',
                                    color: '#00ff00',
                                    weight: 0,
                                    opacity: 1,
                                    fillOpacity: 0.4
                                });
                            } else {
                                // Blocked points - red circles (meter-based, scales with zoom)
                                return L.circle(latlng, {
                                    radius: radius,
                                    fillColor: '#ff0000',
                                    color: '#ff0000',
                                    weight: 0,
                                    opacity: 1,
                                    fillOpacity: 0.3
                                });
                            }
                        }
                    }).addTo(map);

                    // Zoom to fit all points
                    map.fitBounds(viewshedLayer.getBounds(), {padding: [50, 50]});
                })
                .catch(err => {
                    console.error('Error loading viewshed data:', err);
                    showStatus(`Error loading map data: ${err}`, 'error');
                });
        }

        function showResult(jobId, data) {
            const resultsPanel = document.getElementById('results-panel');
            const stats = document.getElementById('stats');

            // Show results panel
            resultsPanel.classList.remove('hidden');

            // Clear previous viewshed data
            if (viewshedLayer) {
                map.removeLayer(viewshedLayer);
            }

            // Load the viewshed data
            loadViewshedData(jobId);

            stats.innerHTML = `
                <div class="stat-item">
                    <div class="stat-value">${data.observer_elevation.toFixed(1)}m</div>
                    <div class="stat-label">Ground Elevation</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${data.observer_height_agl.toFixed(1)}m</div>
                    <div class="stat-label">Antenna Height</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${data.visible_count}</div>
                    <div class="stat-label">Visible Points</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${data.visibility_pct.toFixed(1)}%</div>
                    <div class="stat-label">Visibility</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${data.max_range_km.toFixed(1)}km</div>
                    <div class="stat-label">Max Range</div>
                </div>
            `;
        }

        function pollJob(jobId) {
            fetch(`/status/${jobId}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'running') {
                        showStatus(`Computing viewshed... ${data.progress || ''}`, 'info');
                    } else if (data.status === 'completed') {
                        clearInterval(pollInterval);
                        showStatus('Viewshed computation complete!', 'success');
                        showResult(jobId, data);
                        document.getElementById('submitBtn').disabled = false;
                    } else if (data.status === 'failed') {
                        clearInterval(pollInterval);
                        showStatus(`Error: ${data.error}`, 'error');
                        document.getElementById('submitBtn').disabled = false;
                    }
                })
                .catch(err => {
                    clearInterval(pollInterval);
                    showStatus(`Error polling job: ${err}`, 'error');
                    document.getElementById('submitBtn').disabled = false;
                });
        }

        function submitForm(event) {
            event.preventDefault();

            const formData = {
                lat: parseFloat(document.getElementById('lat').value),
                lon: parseFloat(document.getElementById('lon').value),
                height: parseFloat(document.getElementById('height').value),
                radius: parseFloat(document.getElementById('radius').value),
                grid_points: parseInt(document.getElementById('grid_points').value),
                dem_product: document.getElementById('dem_product').value
            };

            document.getElementById('submitBtn').disabled = true;
            showStatus('Starting viewshed computation...', 'info');

            fetch('/compute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(formData)
            })
            .then(r => r.json())
            .then(data => {
                if (data.job_id) {
                    pollInterval = setInterval(() => pollJob(data.job_id), 2000);
                } else {
                    showStatus('Error: No job ID returned', 'error');
                    document.getElementById('submitBtn').disabled = false;
                }
            })
            .catch(err => {
                showStatus(`Error: ${err}`, 'error');
                document.getElementById('submitBtn').disabled = false;
            });
        }
    </script>
</body>
</html>
        """

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def compute(self):
        """Start a viewshed computation job."""
        params = cherrypy.request.json

        # Validate parameters
        try:
            lat = float(params['lat'])
            lon = float(params['lon'])
            height = float(params['height'])
            radius = float(params['radius'])
            grid_points = int(params.get('grid_points', 25))
            dem_product = params.get('dem_product', 'SRTM3')

            if not (-90 <= lat <= 90):
                raise ValueError("Latitude out of range")
            if not (-180 <= lon <= 180):
                raise ValueError("Longitude out of range")
            if height <= 0:
                raise ValueError("Height must be positive")
            if radius <= 0:
                raise ValueError("Radius must be positive")
            if grid_points < 5 or grid_points > 200:
                raise ValueError("Grid points must be between 5 and 200")

        except (KeyError, ValueError, TypeError) as e:
            cherrypy.response.status = 400
            return {"error": str(e)}

        # Create job
        job_id = uuid.uuid4().hex

        with jobs_lock:
            jobs[job_id] = {
                'status': 'queued',
                'params': params,
                'created': time.time(),
            }

        # Start computation in background thread
        thread = threading.Thread(
            target=self._compute_viewshed_worker,
            args=(job_id, lat, lon, height, radius, grid_points, dem_product)
        )
        thread.daemon = True
        thread.start()

        return {"job_id": job_id}

    def _compute_viewshed_worker(self, job_id, lat, lon, height, radius,
                                  grid_points, dem_product):
        """Background worker to compute viewshed."""
        try:
            with jobs_lock:
                jobs[job_id]['status'] = 'running'
                jobs[job_id]['progress'] = 'Initializing...'

            # Compute viewshed
            viewshed = compute_viewshed(
                lat, lon, height, radius,
                use_local_dem=True, dem_product=dem_product, grid_points=grid_points
            )

            if viewshed is None:
                raise Exception("Viewshed computation returned None")

            # Convert viewshed data to GeoJSON format for interactive map
            # Calculate grid spacing in meters for circle radius
            # Grid covers radius (in km) in each direction with grid_points samples
            # Use approximate: 1 degree latitude = 111 km
            grid_spacing_km = (radius * 2) / (grid_points - 1)  # -1 because N points = N-1 intervals
            grid_spacing_meters = grid_spacing_km * 1000  # convert km to meters

            geojson_data = {
                'type': 'FeatureCollection',
                'properties': {
                    'grid_spacing_meters': grid_spacing_meters
                },
                'features': []
            }

            # Add visible points
            for lat_point, lon_point in viewshed['visible_points']:
                geojson_data['features'].append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [lon_point, lat_point]
                    },
                    'properties': {
                        'visible': True
                    }
                })

            # Add blocked points
            for lat_point, lon_point in viewshed['blocked_points']:
                geojson_data['features'].append({
                    'type': 'Feature',
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [lon_point, lat_point]
                    },
                    'properties': {
                        'visible': False
                    }
                })

            # Add observer location
            geojson_data['features'].append({
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [lon, lat]
                },
                'properties': {
                    'type': 'observer',
                    'height_agl': viewshed['observer_height_agl'],
                    'elevation_msl': viewshed['observer_elevation']
                }
            })

            # Update job status
            total = len(viewshed['visible_points']) + len(viewshed['blocked_points'])
            visibility_pct = 100 * len(viewshed['visible_points']) / total if total > 0 else 0

            with jobs_lock:
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['geojson'] = geojson_data
                jobs[job_id]['observer_lat'] = lat
                jobs[job_id]['observer_lon'] = lon
                jobs[job_id]['observer_elevation'] = viewshed['observer_elevation']
                jobs[job_id]['observer_height_agl'] = viewshed['observer_height_agl']
                jobs[job_id]['visible_count'] = len(viewshed['visible_points'])
                jobs[job_id]['blocked_count'] = len(viewshed['blocked_points'])
                jobs[job_id]['visibility_pct'] = visibility_pct
                jobs[job_id]['max_range_km'] = viewshed['max_range_km']
                jobs[job_id]['completed'] = time.time()

        except Exception as e:
            print(f"Error in viewshed computation: {e}")
            import traceback
            traceback.print_exc()
            with jobs_lock:
                jobs[job_id]['status'] = 'failed'
                jobs[job_id]['error'] = str(e)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def status(self, job_id):
        """Get status of a computation job."""
        with jobs_lock:
            if job_id not in jobs:
                cherrypy.response.status = 404
                return {"error": "Job not found"}

            job = jobs[job_id].copy()

        return job

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def geojson(self, job_id):
        """Get GeoJSON data for a completed viewshed computation."""
        with jobs_lock:
            if job_id not in jobs:
                cherrypy.response.status = 404
                return {"error": "Job not found"}

            job = jobs[job_id]
            if job['status'] != 'completed':
                cherrypy.response.status = 400
                return {"error": "Job not completed"}

            return job.get('geojson', {})


def main():
    """Start the CherryPy web server."""
    print("=" * 70)
    print("VIEWSHED ANALYSIS WEB SERVICE")
    print("=" * 70)
    print(f"Starting server on http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop")
    print("=" * 70)

    cherrypy.config.update({
        'server.socket_host': HOST,
        'server.socket_port': PORT,
        'log.screen': True,
        'engine.autoreload.on': False,
    })

    cherrypy.quickstart(ViewshedServer())


if __name__ == '__main__':
    main()
