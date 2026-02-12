# Docker Deployment for InkStitch API

## Quick Start

### Build the API-only Image (Fast - No wxPython)

```bash
docker build -f Dockerfile.api -t inkstitch-api .
```

Build time: **~2-3 minutes** (vs 20+ minutes with full GUI dependencies)

### Run the Container

```bash
docker run -d \
  --name inkstitch-api \
  -p 8000:8000 \
  -e WORKERS=2 \
  inkstitch-api
```

### Test It

```bash
# Get font list
curl http://localhost:8000/fonts | jq '.[0:3]'

# Generate embroidery
curl -o test.pes "http://localhost:8000/batch_text_to_pes?text=Hello&font=CooperMarif&scale=100"
```

## Why Two Dockerfiles?

### `Dockerfile` (Original - Full InkStitch)
- **Purpose**: Complete InkStitch installation with GUI
- **Size**: ~2GB+
- **Build time**: 20-30 minutes
- **Includes**: wxPython, GTK, all GUI dependencies
- **Use when**: You need the full InkStitch application

### `Dockerfile.api` (Recommended - API Only)
- **Purpose**: FastAPI server only, no GUI
- **Size**: ~500MB
- **Build time**: 2-3 minutes
- **Includes**: Only embroidery generation libraries
- **Use when**: You only need the web API (most cases)

## Production Deployment

### With Docker Compose

Create `docker-compose.yml`:

```yaml
services:
  inkstitch-api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - WORKERS=2
    restart: unless-stopped
    volumes:
      - cache:/tmp/inkstitch_cache
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/fonts"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  cache:
```

Start:
```bash
docker-compose up -d
```

### With Resource Limits

For VPS with limited resources:

```bash
docker run -d \
  --name inkstitch-api \
  -p 8000:8000 \
  --memory=1g \
  --cpus=2 \
  -e WORKERS=2 \
  --restart=unless-stopped \
  inkstitch-api
```

### Behind Nginx (Recommended)

Create `/etc/nginx/sites-available/inkstitch`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Increase timeouts for long embroidery generation
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Cache font list endpoint
    location /fonts {
        proxy_pass http://localhost:8000;
        proxy_cache_valid 200 1h;
        add_header X-Cache-Status $upstream_cache_status;
    }
}
```

Enable and test:
```bash
sudo ln -s /etc/nginx/sites-available/inkstitch /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKERS` | 2 | Number of Gunicorn workers |
| `PYTHONUNBUFFERED` | 1 | Unbuffered Python output |

### Adjust Workers

Based on your VPS specs:

- **1-2 CPU cores**: `WORKERS=2`
- **4 CPU cores**: `WORKERS=4`
- **8+ CPU cores**: `WORKERS=8`

Rule of thumb: `WORKERS = (2 × CPU_CORES) + 1`

## Monitoring

### View Logs

```bash
# Real-time logs
docker logs -f inkstitch-api

# Last 100 lines
docker logs --tail 100 inkstitch-api
```

### Check Health

```bash
# Container status
docker ps | grep inkstitch

# Resource usage
docker stats inkstitch-api

# Font list test
curl -I http://localhost:8000/fonts
```

### Inside the Container

```bash
# Shell access
docker exec -it inkstitch-api bash

# Check Python environment
docker exec inkstitch-api python --version

# List installed packages
docker exec inkstitch-api pip list
```

## Troubleshooting

### Build Fails with "No space left on device"

```bash
# Clean Docker
docker system prune -a

# Check disk space
df -h
```

### Container Crashes on Startup

```bash
# Check logs
docker logs inkstitch-api

# Common issues:
# 1. Port 8000 already in use
sudo lsof -i :8000

# 2. Out of memory
docker stats inkstitch-api
```

### Slow Performance

1. **Check worker count**:
   ```bash
   docker exec inkstitch-api ps aux | grep gunicorn
   ```

2. **Increase memory**:
   ```bash
   docker update --memory=2g inkstitch-api
   ```

3. **Clear cache**:
   ```bash
   docker exec inkstitch-api rm -rf /tmp/inkstitch_cache/*
   ```

### Font List Empty

```bash
# Check if fonts directory exists
docker exec inkstitch-api ls -la /app/fonts

# Rebuild with fonts
docker build --no-cache -f Dockerfile.api -t inkstitch-api .
```

## Updates

### Rebuild Image

```bash
# Pull latest code
git pull

# Rebuild (fast with layer caching)
docker build -f Dockerfile.api -t inkstitch-api .

# Restart container
docker stop inkstitch-api
docker rm inkstitch-api
docker run -d --name inkstitch-api -p 8000:8000 inkstitch-api
```

### Zero-Downtime Update

```bash
# Build new image
docker build -f Dockerfile.api -t inkstitch-api:new .

# Start new container on different port
docker run -d --name inkstitch-api-new -p 8001:8000 inkstitch-api:new

# Test new version
curl http://localhost:8001/fonts

# Switch traffic (update nginx or load balancer)
# Then stop old container
docker stop inkstitch-api
docker rm inkstitch-api

# Rename new container
docker rename inkstitch-api-new inkstitch-api
```

## Performance Benchmarks

Typical performance on a 2-core VPS:

| Metric | Cold Start | Cached |
|--------|-----------|--------|
| Font list | 200-300ms | <5ms |
| Simple text (5 chars) | 1-2s | 20-50ms |
| Complex text (50 chars) | 3-5s | 50-100ms |
| Concurrent requests (5) | 8-12s | 200-500ms |

## Security

### Don't Expose Directly to Internet

Always use:
- Nginx reverse proxy
- HTTPS (Let's Encrypt)
- Rate limiting
- Firewall rules

### Limit Cache Size

Add to docker-compose.yml:

```yaml
volumes:
  cache:
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=500m
```

### Read-Only Filesystem (Advanced)

```bash
docker run -d \
  --name inkstitch-api \
  -p 8000:8000 \
  --read-only \
  --tmpfs /tmp:size=1g \
  inkstitch-api
```

## Cost Optimization

### Use Smaller Instance

The API works on very small VPS instances:

- **Minimum**: 1 vCPU, 1GB RAM ($5/month)
- **Recommended**: 2 vCPU, 2GB RAM ($10-15/month)
- **Optimal**: 2 vCPU, 4GB RAM ($20/month)

### Share with Other Services

Since embroidery generation is sporadic, you can run other services on the same VPS.

## Next Steps

- Set up monitoring (Prometheus + Grafana)
- Add rate limiting (nginx or FastAPI middleware)
- Implement request queueing for high load
- Add CDN for font preview images

For more details, see [PERFORMANCE_OPTIMIZATIONS.md](./PERFORMANCE_OPTIMIZATIONS.md)
