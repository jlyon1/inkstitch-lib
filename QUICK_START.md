# Quick Start - Deploy Optimized InkStitch API

## 🚀 Immediate Deployment (VPS)

### 1. Check Your System

```bash
python check_dependencies.py
```

If you see any ✗ marks, install missing packages:
```bash
# For lxml issues
pip install --force-reinstall lxml

# For system resource monitoring
pip install psutil
```

### 2. Install Gunicorn

```bash
pip install gunicorn
```

### 3. Start the Optimized Server

**Instead of**:
```bash
uvicorn batch_text_to_pes:app --host 0.0.0.0 --port 8000
```

**Use**:
```bash
gunicorn -c gunicorn_config.py batch_text_to_pes:app
```

That's it! Your API is now optimized.

## 🐳 Docker Deployment (Even Easier)

### 1. Build

```bash
docker build -t inkstitch-api .
```

### 2. Run

```bash
docker run -d \
  --name inkstitch-api \
  -p 8000:8000 \
  -e WORKERS=2 \
  inkstitch-api
```

### 3. Check Status

```bash
docker logs -f inkstitch-api
```

## 📊 Test the Improvements

### Before vs After

**Test response time**:
```bash
# First request (cold start)
time curl -o test1.pes "http://localhost:8000/batch_text_to_pes?text=Hello&font=CooperMarif"

# Second request (cached) - should be ~100x faster!
time curl -o test2.pes "http://localhost:8000/batch_text_to_pes?text=Hello&font=CooperMarif"

# Font list (cached) - should be instant
time curl "http://localhost:8000/fonts"
```

### Concurrent Requests

Test multiple requests at once:
```bash
# Run 5 concurrent requests
for i in {1..5}; do
  curl "http://localhost:8000/batch_text_to_pes?text=Test$i&font=CooperMarif" > test$i.pes &
done
wait
```

Before: Sequential processing (~10+ seconds)
After: Parallel processing (~2-3 seconds)

## 🎯 What Changed

| Feature | Status |
|---------|--------|
| Multi-worker support | ✅ 2 workers |
| Output caching | ✅ SHA256-based |
| Font list caching | ✅ In-memory |
| Async processing | ✅ Thread pool |
| Response compression | ✅ GZip |
| File cleanup | ✅ Automatic |

## ⚙️ Configuration

### Adjust Workers (Based on CPU Cores)

Edit `gunicorn_config.py`:
```python
workers = 2  # Change based on your VPS cores
```

Or set via environment:
```bash
WORKERS=2 gunicorn -c gunicorn_config.py batch_text_to_pes:app
```

### Clear Cache

```bash
rm -rf /tmp/inkstitch_cache/*
```

### Monitor Resources

```bash
# Check if workers are running
ps aux | grep gunicorn

# Monitor CPU/memory
top -p $(pgrep -f gunicorn)

# Check cache size
du -sh /tmp/inkstitch_cache/
```

## 🔧 Troubleshooting

### Still Slow?

1. **Check dependencies**:
   ```bash
   python check_dependencies.py
   ```

2. **Verify lxml has C extensions** (most common issue):
   ```bash
   python -c "from lxml import etree; print(hasattr(etree, 'LXML_VERSION'))"
   ```
   Should print `True`. If `False`:
   ```bash
   pip install --upgrade --force-reinstall lxml
   ```

3. **Check system resources**:
   ```bash
   free -h  # Should have free memory
   nproc    # Number of CPU cores
   ```

### Workers Crashing?

Reduce workers or add swap:
```bash
# Reduce workers
WORKERS=1 gunicorn -c gunicorn_config.py batch_text_to_pes:app

# Or add swap (if low memory)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Cache Not Working?

Check permissions:
```bash
ls -la /tmp/inkstitch_cache/
```

If directory missing:
```bash
mkdir -p /tmp/inkstitch_cache
chmod 755 /tmp/inkstitch_cache
```

## 📈 Expected Performance

| Scenario | Time |
|----------|------|
| First request (cold) | 1-3s |
| Cached request | 10-50ms |
| Font list (first) | 100-300ms |
| Font list (cached) | <5ms |
| 5 concurrent requests | 2-4s total |

## 🎓 Learn More

See [PERFORMANCE_OPTIMIZATIONS.md](./PERFORMANCE_OPTIMIZATIONS.md) for:
- Detailed explanations
- Advanced configurations
- Monitoring strategies
- Further optimizations

## 💡 Pro Tips

1. **Use cache warming**: Make a request for common fonts on startup
2. **Monitor cache size**: Add cron job to clean old files
3. **Use reverse proxy**: Nginx in front for static files
4. **Enable access logs**: Track which fonts are most popular

Happy embroidering! 🧵
