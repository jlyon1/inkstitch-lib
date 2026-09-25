# Use Ubuntu 24.04 as base
FROM ubuntu:24.04

# Install Python, uv, and system dependencies (wx dependencies removed)
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3-pip \
    curl \
    git \
    pkg-config \
    gobject-introspection \
    libgirepository-2.0-dev \
    gir1.2-glib-2.0 \
    libcairo2-dev \
    python3-gi \
    libglib2.0-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies using uv
COPY pyproject.toml .
COPY uv.lock .

# inkex's pinned git commit (EXTENSIONS_AT_INKSCAPE_1.4.1) generates its own
# wheel metadata at build time, and that generation is non-deterministic: it
# has produced a clean `Requires-Dist: lxml (>=4.5.0,<6.0.0)` in some builds
# and an invalid one (`>=4.5.0,<5.0.0 || >=5.0.0,<6.0.0` -- not valid PEP 440)
# in others, for the exact same commit. Neither uv nor pip will install a
# wheel whose metadata they can't parse, so a build can fail on this even
# though a working build of the identical source is entirely possible --
# confirmed by vendor/inkex, a real successful build of this commit. Installed
# from there directly rather than re-built, sidestepping the flaky step.
RUN uv sync --no-install-package inkex

# Copy the rest of the app
COPY . .

COPY vendor/inkex .venv/lib/python3.12/site-packages/inkex
COPY vendor/inkex-1.4.1.dist-info .venv/lib/python3.12/site-packages/inkex-1.4.1.dist-info

# Expose FastAPI port
EXPOSE 8000

# Set environment variables for production
ENV PYTHONUNBUFFERED=1
ENV WORKERS=2

# Install gunicorn in the uv environment
RUN uv pip install gunicorn

# Start FastAPI app with Gunicorn + Uvicorn workers for better concurrency
CMD ["uv", "run", "gunicorn", "-c", "gunicorn_config.py", "batch_text_to_pes:app"]
