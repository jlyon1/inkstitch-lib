"""
Gunicorn configuration for production deployment

Usage:
    gunicorn -c gunicorn_config.py batch_text_to_pes:app
"""

import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
# Use 2 workers for 1-2 core VPS (leaves room for OS)
workers = int(os.getenv("WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = 120  # 2 minutes for long embroidery generation
keepalive = 5

# Restart workers after this many requests to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "inkstitch-api"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (configure if needed)
# keyfile = "/path/to/key.pem"
# certfile = "/path/to/cert.pem"

# For debugging
# reload = True  # Auto-reload on code changes (dev only)
