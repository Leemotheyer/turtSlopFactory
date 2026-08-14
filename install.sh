#!/usr/bin/env bash
# One-command install for turtSlopFactory
set -euo pipefail

REPO="${FACTORY_REPO:-https://github.com/Leemotheyer/turtSlopFactory.git}"
DIR="${FACTORY_DIR:-turtslopfactory}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker first: https://docs.docker.com/get-docker/"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "Docker Compose is required."
  exit 1
fi

if [ ! -d "$DIR" ]; then
  echo "Cloning $REPO ..."
  git clone --depth 1 "$REPO" "$DIR"
fi

cd "$DIR"
echo "Pulling images ..."
$COMPOSE pull
echo "Starting turtSlopFactory ..."
$COMPOSE up -d

HOST="${FACTORY_HOST:-localhost}"
echo ""
echo "✓ turtSlopFactory is running"
echo "  Dashboard: http://${HOST}:8044"
echo "  Live previews: http://${HOST}:9010–9039"
echo ""
echo "Optional: connect Cursor and set an API key from the Cursor menu in the dashboard."
