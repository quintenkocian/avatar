#!/usr/bin/env bash
# Avatar — stop and remove the running Docker container (macOS / Linux).
#
# Usage (from anywhere):  ./scripts/stop_mac.sh
set -euo pipefail

# Docker must be running to talk to it.
if ! docker info >/dev/null 2>&1; then
  echo "Docker does not appear to be running. Start Docker and try again." >&2
  exit 1
fi

echo "Stopping and removing 'avatar' container..."
docker rm -f avatar >/dev/null 2>&1 || true

echo "Stopped."
