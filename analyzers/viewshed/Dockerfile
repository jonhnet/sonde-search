# Viewshed Analysis Web Service Container
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    make \
    curl \
    unzip \
    gzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY viewshed_server.py .
COPY viewshed.py .
COPY dem_manager.py .
COPY optimize.html .
COPY static/ ./static/

# Create cache directory for DEM tiles
RUN mkdir -p /cache/srtm && chmod 777 /cache/srtm

# Expose port
EXPOSE 6565

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV ELEVATION_CACHE_DIR=/cache/srtm

# Run the server
CMD ["python", "viewshed_server.py"]
