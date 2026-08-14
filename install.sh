#!/usr/bin/env bash
# One-command install for turtSlopFactory
set -euo pipefail

REPO="${FACTORY_REPO:-https://github.com/Leemotheyer/turtSlopFactory.git}"
DIR="${FACTORY_DIR:-turtslopfactory}"
DATA="${FACTORY_DATA:-./data}"

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
mkdir -p "${DATA}/config" "${DATA}/workspaces" "${DATA}/postgres" "${DATA}/redis"
if [ ! -f "${DATA}/config/local.env" ] && [ -f "${DATA}/config/local.env.example" ]; then
  cp "${DATA}/config/local.env.example" "${DATA}/config/local.env"
fi
echo "Pulling image ..."
FACTORY_DATA="$DATA" $COMPOSE pull
echo "Starting turtSlopFactory ..."
FACTORY_DATA="$DATA" $COMPOSE up -d

HOST="${FACTORY_HOST:-localhost}"
PORT="${HTTP_PORT:-8044}"
echo ""
echo "✓ turtSlopFactory is running (single container)"
echo "  Dashboard: http://${HOST}:${PORT}"
echo "  Data directory: ${DATA}"
echo "  Live previews: http://${HOST}:${PORT}/preview/<project-id>/"
echo ""
echo "Optional: connect Cursor and set an API key from the Cursor menu in the dashboard."
