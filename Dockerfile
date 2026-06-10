# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# Avatar — single-container build.
# Stage 1 (web): build the Vite frontend into /frontend/dist.
# Stage 2 (app): install the FastAPI backend with uv, copy the built static
#                assets + knowledge, and run uvicorn.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: build the frontend ──────────────────────────────────────────────
FROM node:24-alpine AS web

WORKDIR /frontend

# Install dependencies first (better layer caching). Copy only the manifests so
# this layer is reused when only source files change. The package-lock.json may
# or may not exist, so the glob keeps the COPY happy either way.
COPY frontend/package.json frontend/package-lock.json* ./
# Prefer the reproducible `npm ci` (needs a lockfile); fall back to `npm install`.
RUN npm ci || npm install

# Copy the rest of the frontend source and build it.
COPY frontend/ ./
RUN npm run build

# ── Stage 2: run the backend ─────────────────────────────────────────────────
FROM python:3.12-slim AS app

# uv: fast, reproducible Python dependency management (copied from the official
# distroless uv image — no curl/install script needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# uv settings: install into the system environment (no project venv layer to
# carry around) and copy rather than hardlink across the layer boundary.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install dependencies first using only the lock + manifest for cache reuse.
# `--frozen` requires uv.lock to be in sync with pyproject.toml; if this build
# of uv doesn't support the flag (older builds), fall back to a plain sync.
# `--no-install-project` installs only the third-party deps, NOT the local
# `backend` package — the app is run from source via `--app-dir .` at runtime,
# and pyproject.toml declares no build backend, so we never need to build it.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-install-project --no-dev \
    || uv sync --no-install-project --no-dev

# Copy the backend application code so `app.main` resolves at runtime.
COPY backend/ ./

# Copy the owner knowledge and the built frontend into their runtime locations.
COPY knowledge/ /app/knowledge/
COPY --from=web /frontend/dist /app/static

# Runtime configuration. KNOWLEDGE_DIR / STATIC_DIR are read by app.config;
# PORT is read by the CMD below (Fly also injects it).
ENV KNOWLEDGE_DIR=/app/knowledge \
    STATIC_DIR=/app/static \
    PORT=8000 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Run uvicorn via uv so it uses the synced environment. `--no-sync` skips any
# re-resolution at startup (deps are already installed). `sh -c` lets ${PORT}
# expand at runtime (so Fly can override it). --app-dir . keeps `app.main`
# importable from the /app working directory.
CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --app-dir ."]
