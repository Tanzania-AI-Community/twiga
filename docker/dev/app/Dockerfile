# syntax = docker/dockerfile:1.2
# need syntax v1.2 for secret mounts (preferred by Render)

# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim as twiga-dev

WORKDIR /src

# Copy dependency files first to leverage caching
COPY pyproject.toml uv.lock ./

RUN ls -la /src

# Install dependencies
RUN uv sync --frozen --no-cache

# Copy application code
COPY . .

# Fastapi port
EXPOSE 8000

WORKDIR /app

# Run the application
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/app"]
