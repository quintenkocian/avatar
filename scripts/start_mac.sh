#!/usr/bin/env bash
# Avatar — build and run the single Docker container (macOS / Linux).
#
# Stops and removes any existing `avatar` container, rebuilds the image from the
# repo root, then runs it with the root .env on port 8000.
#
# Usage (from anywhere):  ./scripts/start_mac.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Docker must be running.
if ! docker info >/dev/null 2>&1; then
  echo "Docker does not appear to be running. Start Docker and try again." >&2
  exit 1
fi

# The container reads configuration from the root .env via --env-file.
if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "No .env found at repo root. Copy the values from README.md 'Setup instructions' first." >&2
  exit 1
fi

echo "Stopping any existing 'avatar' container..."
docker rm -f avatar >/dev/null 2>&1 || true

echo "Building image 'avatar'..."
docker build -t avatar .

echo "Starting container 'avatar' on port 8000..."
docker run -d --name avatar --env-file .env -p 8000:8000 avatar >/dev/null

echo
echo "Avatar is running:"
echo "  Visitor:  http://localhost:8000"
echo "  Admin:    http://localhost:8000/admin"
echo
echo "Logs:  docker logs -f avatar"
echo "Stop:  ./scripts/stop_mac.sh"
