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
from viewshed import compute_viewshed, plot_viewshed, optimize_coverage
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
    def optimize_ui(self):
        """Serve the optimization UI."""
        html_path = Path(__file__).parent / 'optimize.html'
        with open(html_path, 'r') as f:
            return f.read()

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
    <link rel="stylesheet" href="static/sidebar.css" />
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

            <div style="margin-bottom: 20px;">
                <a href="optimize_ui" style="display: inline-block; background: #2196F3; color: white; text-decoration: none; padding: 10px 20px; border-radius: 4px; font-weight: 600; font-size: 14px;">
                    🎯 Coverage Optimization Tool →
                </a>
            </div>

            <div style="background: #e3f2fd; border: 1px solid #2196F3; color: #1976D2; padding: 10px; border-radius: 4px; margin-bottom: 20px; font-size: 13px;">
                <b>💡 Tip:</b> Click anywhere on the map to set the antenna location
            </div>

        <form id="viewshedForm" onsubmit="submitForm(event)">
            <div class="form-group" style="grid-column: 1 / -1;">
                <label>
                    Location (Lat, Lon)
                    <div class="label-help">Paste from Google Maps or enter as "lat, lon"</div>
                </label>
                <input type="text" id="latlng" placeholder="47.6062, -122.3321" value="47.6062, -122.3321" required>
                <input type="hidden" id="lat" value="47.6062">
                <input type="hidden" id="lon" value="-122.3321">
            </div>

            <div class="form-grid">

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
                            <option value="SRTM3">SRTM3 (90m, global)</option>
                            <option value="SRTM_BEST" selected>SRTM Best (adaptive)</option>
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
            <button class="toggle-sidebar" id="toggle-sidebar" onclick="toggleSidebar()">☰</button>
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

            // Parse current lat/lon from the input field
            const parsed = parseLatLon();
            const lat = parsed ? parsed.lat : center.lat;
            const lon = parsed ? parsed.lon : center.lng;

            const state = {
                lat: lat,
                lon: lon,
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
                    updateInputFromLatLon(pos.lat, pos.lng);
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

                // Update form fields with saved antenna location (if valid)
                if (savedState.lat != null && savedState.lon != null &&
                    !isNaN(savedState.lat) && !isNaN(savedState.lon)) {
                    updateInputFromLatLon(savedState.lat, savedState.lon);
                } else {
                    // Fallback to map center if antenna location is invalid
                    updateInputFromLatLon(initialLat, initialLon);
                }
            } else {
                // Parse defaults from latlng text field
                const parsed = parseLatLon();
                if (parsed) {
                    initialLat = parsed.lat;
                    initialLon = parsed.lon;
                    // Update hidden fields
                    document.getElementById('lat').value = parsed.lat;
                    document.getElementById('lon').value = parsed.lon;
                } else {
                    // Fallback to hardcoded defaults if parsing fails
                    initialLat = 47.6062;
                    initialLon = -122.3321;
                    updateInputFromLatLon(initialLat, initialLon);
                }
                initialZoom = 8;
            }

            map = L.map('map').setView([initialLat, initialLon], initialZoom);

            // Define base layers
            const terrainLayer = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
                attribution: 'Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)',
                maxZoom: 17
            });

            const aerialLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: 'Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
                maxZoom: 19
            });

            // Add default layer (terrain)
            terrainLayer.addTo(map);

            // Add layer control for switching between terrain and aerial
            // Position at bottom-right to avoid overlap with sidebar toggle button
            const baseMaps = {
                "Terrain": terrainLayer,
                "Aerial": aerialLayer
            };
            L.control.layers(baseMaps, null, { position: 'bottomright' }).addTo(map);

            // Draw initial antenna marker from form values
            setAntennaMarker(initialLat, initialLon);

            // Save state when map moves
            map.on('moveend', saveState);
            map.on('zoomend', saveState);

            // Add click handler to set antenna location
            map.on('click', function(e) {
                const lat = e.latlng.lat;
                const lon = e.latlng.lng;

                // Update form fields
                updateInputFromLatLon(lat, lon);

                // Update marker
                setAntennaMarker(lat, lon);
                selectedMarker.openPopup();

                // Save state
                saveState();
            });

            // Save state when latlng input changes
            document.getElementById('latlng').addEventListener('change', updateLatLonFromInput);
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
                    dem_product: 'SRTM_BEST'
                },
                detailed: {
                    radius: 100,
                    grid_points: 50,
                    dem_product: 'SRTM_BEST'
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
            fetch(`geojson/${jobId}`)
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

            let statsHTML = `
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

            // Add DEM resolution statistics if available
            if (data.dem_stats) {
                const srtm1_pct = (data.dem_stats.srtm1_queries / data.dem_stats.total_queries * 100).toFixed(1);
                const srtm3_pct = (data.dem_stats.srtm3_fallback_queries / data.dem_stats.total_queries * 100).toFixed(1);
                statsHTML += `
                    <div class="stat-item" style="grid-column: 1 / -1; margin-top: 10px; padding-top: 10px; border-top: 1px solid #e0e0e0;">
                        <div class="stat-label" style="font-weight: 600; margin-bottom: 8px;">DEM Resolution</div>
                        <div style="font-size: 13px; color: #666;">
                            SRTM1 (30m): ${srtm1_pct}% • SRTM3 (90m): ${srtm3_pct}%
                        </div>
                    </div>
                `;
            }

            stats.innerHTML = statsHTML;
        }

        function pollJob(jobId) {
            fetch(`status/${jobId}`)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'running') {
                        let statusMsg = 'Computing viewshed...';
                        if (data.progress_message) {
                            // Use custom progress message if provided
                            statusMsg = data.progress_message;
                        } else if (data.progress_completed && data.progress_total) {
                            const pct = Math.round(100 * data.progress_completed / data.progress_total);
                            statusMsg = `Computing viewshed... ${pct}% (${data.progress_completed}/${data.progress_total} points)`;
                        } else if (data.progress) {
                            statusMsg = `Computing viewshed... ${data.progress}`;
                        }
                        showStatus(statusMsg, 'info');
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

        // Parse lat/lon from text input (supports Google Maps format and simple "lat, lon")
        function parseLatLon() {
            const input = document.getElementById('latlng').value.trim();

            // Try to parse various formats:
            // "47.6062, -122.3321"
            // "47.6062,-122.3321"
            // "-122.3321, 47.6062" (Google Maps copy format - lon, lat)

            // Remove any parentheses or extra whitespace
            const cleaned = input.replace(/[()]/g, '').trim();

            // Split by comma
            const parts = cleaned.split(',').map(p => p.trim());

            if (parts.length !== 2) {
                return null;
            }

            const num1 = parseFloat(parts[0]);
            const num2 = parseFloat(parts[1]);

            if (isNaN(num1) || isNaN(num2)) {
                return null;
            }

            // Detect which is lat and which is lon
            // Latitude is always -90 to 90, longitude is -180 to 180
            // If first number is in lat range and second is outside, assume lat, lon
            // If first number is outside lat range, assume it's lon, lat (Google Maps format)
            let lat, lon;

            if (Math.abs(num1) <= 90 && Math.abs(num2) <= 180) {
                // Could be either format, assume lat, lon (most common)
                lat = num1;
                lon = num2;
            } else if (Math.abs(num2) <= 90 && Math.abs(num1) <= 180) {
                // First number is out of lat range, must be lon, lat
                lon = num1;
                lat = num2;
            } else {
                return null;
            }

            // Validate ranges
            if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
                return null;
            }

            return { lat, lon };
        }

        // Update hidden lat/lon fields when latlng input changes
        function updateLatLonFromInput() {
            const parsed = parseLatLon();
            if (parsed) {
                document.getElementById('lat').value = parsed.lat;
                document.getElementById('lon').value = parsed.lon;

                // Update marker if it exists
                if (selectedMarker) {
                    setAntennaMarker(parsed.lat, parsed.lon);
                }

                saveState();
            }
        }

        // Update the latlng text field from lat/lon values
        function updateInputFromLatLon(lat, lon) {
            document.getElementById('latlng').value = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
            document.getElementById('lat').value = lat;
            document.getElementById('lon').value = lon;
        }

        function submitForm(event) {
            event.preventDefault();

            // Parse lat/lon from input
            const parsed = parseLatLon();
            if (!parsed) {
                showStatus('Error: Invalid lat/lon format. Use "lat, lon" format.', 'error');
                return;
            }

            const formData = {
                lat: parsed.lat,
                lon: parsed.lon,
                height: parseFloat(document.getElementById('height').value),
                radius: parseFloat(document.getElementById('radius').value),
                grid_points: parseInt(document.getElementById('grid_points').value),
                dem_product: document.getElementById('dem_product').value
            };

            document.getElementById('submitBtn').disabled = true;
            showStatus('Starting viewshed computation...', 'info');

            fetch('compute', {
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
    <script src="static/sidebar.js"></script>
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

            # Define progress callback
            def update_progress(completed, total, message):
                with jobs_lock:
                    jobs[job_id]['progress_completed'] = completed
                    jobs[job_id]['progress_total'] = total
                    jobs[job_id]['progress_message'] = message

            # Compute viewshed
            viewshed = compute_viewshed(
                lat, lon, height, radius,
                use_local_dem=True, dem_product=dem_product, grid_points=grid_points,
                progress_callback=update_progress
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
                # Include DEM statistics if available
                if 'dem_stats' in viewshed:
                    jobs[job_id]['dem_stats'] = viewshed['dem_stats']

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

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def optimize(self):
        """
        Optimize receiver placement for target area coverage.

        POST body:
        {
            "target_bounds": {"min_lat": ..., "max_lat": ..., "min_lon": ..., "max_lon": ...},
            "search_bounds": {"min_lat": ..., "max_lat": ..., "min_lon": ..., "max_lon": ...},
            "height": 10,
            "target_grid_size": 20,
            "search_grid_size": 10,
            "top_k": 5,
            "hill_climb_steps": 10,
            "dem_product": "SRTM3"
        }
        """
        try:
            params = cherrypy.request.json

            # Validate required parameters
            required = ['target_bounds', 'search_bounds', 'height']
            for field in required:
                if field not in params:
                    cherrypy.response.status = 400
                    return {"error": f"Missing required field: {field}"}

            # Validate bounds structure
            for bounds_name in ['target_bounds', 'search_bounds']:
                bounds = params[bounds_name]
                required_keys = ['min_lat', 'max_lat', 'min_lon', 'max_lon']
                for key in required_keys:
                    if key not in bounds:
                        cherrypy.response.status = 400
                        return {"error": f"Missing {key} in {bounds_name}"}

            # Create job
            job_id = str(uuid.uuid4())
            with jobs_lock:
                jobs[job_id] = {
                    'id': job_id,
                    'status': 'running',
                    'type': 'optimization',
                    'params': params
                }

            # Start background thread
            thread = threading.Thread(target=self._run_optimization, args=(job_id,))
            thread.daemon = True
            thread.start()

            return {"job_id": job_id}

        except Exception as e:
            cherrypy.response.status = 500
            return {"error": str(e)}

    def _run_optimization(self, job_id):
        """Background worker for coverage optimization."""
        try:
            with jobs_lock:
                params = jobs[job_id]['params']

            # Extract parameters
            target_bounds = params['target_bounds']
            search_bounds = params['search_bounds']
            height = float(params['height'])
            target_grid_size = int(params.get('target_grid_size', 20))
            search_grid_size = int(params.get('search_grid_size', 10))
            top_k = int(params.get('top_k', 5))
            hill_climb_steps = int(params.get('hill_climb_steps', 10))
            dem_product = params.get('dem_product', 'SRTM3')

            # Progress callback to update job status
            def update_progress(completed, total, message):
                with jobs_lock:
                    jobs[job_id]['progress_completed'] = completed
                    jobs[job_id]['progress_total'] = total
                    jobs[job_id]['progress_message'] = message

            # Run optimization
            result = optimize_coverage(
                target_bounds=target_bounds,
                search_bounds=search_bounds,
                observer_height_agl=height,
                target_grid_size=target_grid_size,
                search_grid_size=search_grid_size,
                top_k=top_k,
                hill_climb_steps=hill_climb_steps,
                dem_product=dem_product,
                progress_callback=update_progress
            )

            # Store results
            with jobs_lock:
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['best_location'] = result['best_location']
                jobs[job_id]['best_coverage_pct'] = result['best_coverage_pct']
                jobs[job_id]['all_candidates'] = result['all_candidates']
                jobs[job_id]['target_points'] = result['target_points']

        except Exception as e:
            with jobs_lock:
                jobs[job_id]['status'] = 'failed'
                jobs[job_id]['error'] = str(e)


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

    # Configure static file serving
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    config = {
        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': static_dir
        }
    }

    cherrypy.quickstart(ViewshedServer(), '/', config)


if __name__ == '__main__':
    main()
