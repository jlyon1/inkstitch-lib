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

RUN uv sync

# Copy the rest of the app
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Set environment variables for production
ENV PYTHONUNBUFFERED=1
ENV WORKERS=2

# Install gunicorn in the uv environment
RUN uv pip install gunicorn

# Start FastAPI app with Gunicorn + Uvicorn workers for better concurrency
CMD ["uv", "run", "gunicorn", "-c", "gunicorn_config.py", "batch_text_to_pes:app"]
