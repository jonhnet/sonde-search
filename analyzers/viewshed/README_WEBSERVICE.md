# Viewshed Analysis Web Service

A CherryPy-based web interface for computing and visualizing antenna viewsheds.

## Quick Start

1. **Install dependencies** (if not already installed):
   ```bash
   pip install -r ../requirements.txt
   ```

2. **Start the server**:
   ```bash
   ./viewshed_server.py
   ```

3. **Open your browser**:
   ```
   http://localhost:6565
   ```

## Features

- **Interactive web interface**: Easy-to-use form with presets
- **Real-time progress**: Watch the computation progress
- **Asynchronous processing**: Jobs run in background threads
- **Automatic caching**: DEM tiles cached for fast re-analysis
- **Responsive design**: Works on desktop and mobile

## Web Interface

### Main Form

- **Latitude/Longitude**: Antenna location in decimal degrees
- **Antenna Height**: Height above ground in meters
- **Analysis Radius**: How far to analyze in kilometers

### Advanced Options

- **Resolution**: Range ring spacing (lower = more detail, slower)
- **Radials**: Number of bearings to test (more = higher accuracy)
- **DEM Product**: SRTM1 (30m, better) or SRTM3 (90m, faster)

### Presets

- **Quick Preview**: 30km radius, 2km resolution, 24 radials (~200 points, ~10 seconds)
- **Standard**: 50km radius, 1km resolution, 36 radials (~1800 points, ~30 seconds)
- **High Detail**: 100km radius, 0.5km resolution, 72 radials (~14,000 points, ~3 minutes)

## API Endpoints

### POST `/compute`

Start a new viewshed computation.

**Request body** (JSON):
```json
{
  "lat": 47.6062,
  "lon": -122.3321,
  "height": 10,
  "radius": 50,
  "resolution": 1.0,
  "radials": 36,
  "dem_product": "SRTM3"
}
```

**Response**:
```json
{
  "job_id": "a1b2c3d4e5f6..."
}
```

### GET `/status/<job_id>`

Get the status of a computation job.

**Response** (running):
```json
{
  "status": "running",
  "progress": "Testing 1200/1800 points",
  "created": 1234567890.0
}
```

**Response** (completed):
```json
{
  "status": "completed",
  "observer_elevation": 125.3,
  "observer_height_agl": 10.0,
  "visible_count": 1584,
  "blocked_count": 216,
  "visibility_pct": 88.0,
  "max_range_km": 49.5,
  "created": 1234567890.0,
  "completed": 1234567920.0
}
```

**Response** (failed):
```json
{
  "status": "failed",
  "error": "Could not determine observer elevation"
}
```

### GET `/image/<job_id>`

Get the generated viewshed image (PNG).

**Response**: PNG image file

## Example cURL Usage

```bash
# Start computation
JOB_ID=$(curl -X POST http://localhost:6565/compute \
  -H "Content-Type: application/json" \
  -d '{"lat": 47.6, "lon": -122.3, "height": 10, "radius": 50}' \
  | jq -r '.job_id')

# Check status
curl http://localhost:6565/status/$JOB_ID | jq

# Download image
curl http://localhost:6565/image/$JOB_ID -o viewshed.png
```

## Configuration

Edit `viewshed_server.py` to change:

```python
PORT = 6565              # Server port
HOST = '0.0.0.0'         # Listen address (0.0.0.0 = all interfaces)
OUTPUT_DIR = Path('/tmp/viewshed_outputs')  # Where to save images
```

## Architecture

### Frontend
- Single-page HTML/CSS/JavaScript interface
- Polling-based job status updates (every 2 seconds)
- Responsive design with form validation

### Backend
- **CherryPy**: Web framework
- **Threading**: Async job processing
- **In-memory job storage**: Job metadata stored in dict (not persistent)
- **Filesystem**: Generated images saved to `/tmp/viewshed_outputs/`

### Job Lifecycle

1. User submits form → POST to `/compute`
2. Server creates job with unique ID
3. Background thread starts viewshed computation
4. Frontend polls `/status/<job_id>` every 2 seconds
5. When complete, frontend displays image from `/image/<job_id>`

## Performance Notes

- **First run**: Downloads DEM tiles (~30-60 seconds)
- **Subsequent runs**: Uses cached tiles (much faster)
- **Concurrent jobs**: Multiple users can submit jobs simultaneously
- **Memory**: Jobs stored in RAM (restart clears all jobs)

## Limitations

- **Job persistence**: Jobs lost on server restart
- **File cleanup**: Old images not automatically deleted
- **Scaling**: Single-threaded computation (one CPU core per job)
- **Security**: No authentication, intended for localhost use

## Production Deployment

For production use, consider:

1. **Add authentication**: Protect endpoints with user auth
2. **Persistent storage**: Store job metadata in database
3. **File cleanup**: Periodic cleanup of old images
4. **Rate limiting**: Prevent abuse
5. **Process pool**: Use multiprocessing for parallel jobs
6. **HTTPS**: Use reverse proxy (nginx) with SSL
7. **Monitoring**: Add logging and metrics

Example nginx config:
```nginx
server {
    listen 80;
    server_name viewshed.example.com;

    location / {
        proxy_pass http://localhost:6565;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Troubleshooting

**Port already in use**:
```bash
# Change PORT in viewshed_server.py or kill existing process
lsof -ti:6565 | xargs kill
```

**Jobs not completing**:
- Check server console for errors
- Verify DEM tiles can be downloaded
- Check disk space in `/tmp/`

**Slow performance**:
- Use SRTM3 instead of SRTM1
- Reduce radius or increase resolution
- Reduce number of radials

## Integration with Other Tools

The web service can be integrated with other sonde tracking tools:

```python
import requests

# Compute viewshed for a receiver location
response = requests.post('http://localhost:6565/compute', json={
    'lat': receiver_lat,
    'lon': receiver_lon,
    'height': 10,
    'radius': 100
})

job_id = response.json()['job_id']

# Poll until complete
while True:
    status = requests.get(f'http://localhost:6565/status/{job_id}').json()
    if status['status'] == 'completed':
        print(f"Max range: {status['max_range_km']}km")
        break
    time.sleep(2)
```

## See Also

- `README_VIEWSHED.md` - CLI tool documentation
- `viewshed.py` - Command-line interface
- `dem_manager.py` - DEM tile management
