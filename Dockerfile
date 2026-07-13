# ---------- Stage 1: build the Flutter web app (served by the backend at /app) ----------
FROM ghcr.io/cirruslabs/flutter:stable AS flutter-web

WORKDIR /build
# CI builders (Coolify) run as root; the SDK checkout may be owned differently
RUN git config --global --add safe.directory '*'

# Dependency layer — only re-runs when pubspec changes
COPY mobile/pubspec.yaml mobile/pubspec.lock ./
RUN flutter pub get

COPY mobile/ ./
RUN flutter build web --release --base-href /app/

# ---------- Stage 2: Python backend ----------
FROM python:3.11-slim

# Copy uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when pyproject.toml or uv.lock changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/

# Flutter web bundle — app/main.py mounts this at /app when present
COPY --from=flutter-web /build/build/web ./mobile/build/web

# Persistent SQLite data directory
RUN mkdir -p /app/data

ENV DATABASE_URL=sqlite+aiosqlite:///./data/tennis.db
ENV PYTHONUNBUFFERED=1
# Trust X-Forwarded-* from the reverse proxy (Coolify/Traefik) so the app sees
# the real client IP (rate limiting) and https scheme (Secure cookies, HSTS).
# The container is only reachable through the proxy on the Docker network.
ENV FORWARDED_ALLOW_IPS=*

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
