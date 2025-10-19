# Viewshed Service Deployment Guide

## Quick Start with Podman/Docker

### 1. Build and Run Locally

```bash
# Using Docker Compose (works with podman-compose too)
cd /path/to/sonde-search/analyzers
docker-compose up -d

# Or using Podman directly
podman build -t viewshed-server .
podman run -d \
  --name viewshed \
  -p 6565:6565 \
  -v viewshed-cache:/cache/srtm \
  --restart unless-stopped \
  viewshed-server
```

### 2. Test the Service

```bash
# Check if it's running
curl http://localhost:6565

# Test computation
curl -X POST http://localhost:6565/compute \
  -H "Content-Type: application/json" \
  -d '{"lat": 47.6, "lon": -122.3, "height": 10, "radius": 50, "grid_points": 25}'
```

### 3. Deploy on Remote Server

**Copy files to server:**
```bash
scp -r analyzers/ user@your-server.com:/opt/viewshed/
```

**On the server:**
```bash
cd /opt/viewshed/analyzers
podman-compose up -d

# Or with systemd for auto-start
sudo podman generate systemd --new --name viewshed > /etc/systemd/system/viewshed.service
sudo systemctl enable viewshed
sudo systemctl start viewshed
```

## Nginx Reverse Proxy Setup

### 1. Install Nginx

```bash
sudo apt update
sudo apt install nginx
```

### 2. Configure Site

```bash
# Copy the example config
sudo cp nginx-example.conf /etc/nginx/sites-available/viewshed

# Edit with your domain
sudo nano /etc/nginx/sites-available/viewshed

# Enable the site
sudo ln -s /etc/nginx/sites-available/viewshed /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### 3. Setup SSL with Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate (automatically configures nginx)
sudo certbot --nginx -d viewshed.example.com

# Auto-renewal is configured automatically
sudo certbot renew --dry-run
```

## Podman-Specific Notes

### Using Podman Compose

```bash
# Install podman-compose if not present
pip3 install podman-compose

# Run with podman-compose
podman-compose up -d
```

### Rootless Podman

If running as non-root user:

```bash
# Map privileged port if needed
sudo sysctl net.ipv4.ip_unprivileged_port_start=80

# Or use different port and proxy through nginx
# (recommended - already configured in docker-compose.yml)
```

### Systemd Integration

```bash
# Generate systemd unit file
podman generate systemd --new --name viewshed-server \
  > ~/.config/systemd/user/viewshed.service

# Enable user service
systemctl --user enable viewshed
systemctl --user start viewshed

# Enable linger (keep running when logged out)
loginctl enable-linger $USER
```

## Persistent Data

DEM tile cache is stored in a Docker/Podman volume:

```bash
# Inspect volume
docker volume inspect analyzers_viewshed-cache
# or
podman volume inspect analyzers_viewshed-cache

# Backup cache
docker run --rm -v analyzers_viewshed-cache:/data -v $(pwd):/backup \
  alpine tar czf /backup/viewshed-cache-backup.tar.gz /data

# Restore cache
docker run --rm -v analyzers_viewshed-cache:/data -v $(pwd):/backup \
  alpine tar xzf /backup/viewshed-cache-backup.tar.gz -C /
```

## Monitoring and Logs

```bash
# View logs
docker-compose logs -f
# or
podman logs -f viewshed-server

# Check resource usage
docker stats viewshed-server
# or
podman stats viewshed-server
```

## Updating the Service

```bash
# Pull latest code
cd /opt/viewshed/analyzers
git pull

# Rebuild and restart
docker-compose down
docker-compose build
docker-compose up -d

# Or with Podman
podman stop viewshed-server
podman rm viewshed-server
podman build -t viewshed-server .
podman run -d --name viewshed-server -p 6565:6565 \
  -v viewshed-cache:/cache/srtm --restart unless-stopped viewshed-server
```

## Security Considerations

1. **Rate Limiting**: Consider adding nginx rate limiting:
   ```nginx
   limit_req_zone $binary_remote_addr zone=viewshed:10m rate=10r/m;
   limit_req zone=viewshed burst=5;
   ```

2. **Authentication**: For private deployment, add basic auth:
   ```bash
   sudo apt install apache2-utils
   sudo htpasswd -c /etc/nginx/.htpasswd username
   ```

   In nginx config:
   ```nginx
   auth_basic "Viewshed Service";
   auth_basic_user_file /etc/nginx/.htpasswd;
   ```

3. **Firewall**: Only expose nginx port:
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

## Troubleshooting

**Port already in use:**
```bash
sudo lsof -i :6565
sudo kill <PID>
```

**Container won't start:**
```bash
# Check logs
podman logs viewshed-server

# Check if port is available
ss -tlnp | grep 6565
```

**DEM downloads failing:**
```bash
# Test network from container
podman exec viewshed-server curl -I https://s3.amazonaws.com

# Check cache permissions
podman exec viewshed-server ls -la /cache/srtm
```

**High memory usage:**
```bash
# Adjust memory limits in docker-compose.yml
# Reduce concurrent job processing in viewshed_server.py
```
