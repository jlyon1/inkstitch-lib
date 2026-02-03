# Use Ubuntu 24.04 as base
FROM ubuntu:24.04

# Install Python, uv, and system dependencies
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
    libgtk-3-dev \
    libjpeg-dev \
    libtiff-dev \
    libsdl2-dev \
    libpng-dev \
    libwebkitgtk-6.0-dev \
    libnotify-dev \
    libsm-dev \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    freeglut3-dev \
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

# Start FastAPI app with uv
CMD ["uv", "run", "uvicorn", "batch_text_to_pes:app", "--host", "0.0.0.0", "--port", "8000"]
