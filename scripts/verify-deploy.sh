#!/usr/bin/env bash
# Quick smoke test for deploy files (run on host with bash, no docker required)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Checking deploy scripts..."
for f in deploy/entrypoint.sh deploy/wait-for-services.sh deploy/start-postgres.sh deploy/healthcheck.sh; do
  test -x "$f" || test -f "$f"
  bash -n "$f"
done

echo "Checking compose files reference turtslopfactory image..."
grep -q 'ghcr.io/leemotheyer/turtslopfactory' docker-compose.yml
grep -q 'ghcr.io/leemotheyer/turtslopfactory' portainer-stack.yml

echo "Checking Dockerfile.factory includes git and node..."
grep -q '\bgit\b' Dockerfile.factory
grep -q 'node-runtime' Dockerfile.factory
grep -q 'bookworm-slim AS dashboard-build' Dockerfile.factory

echo "Checking orchestrator startup order..."
grep -A2 'async def lifespan' orchestrator/app/main.py | grep -q init_db
python3 -c "
from pathlib import Path
text = Path('orchestrator/app/main.py').read_text()
i = text.index('async def lifespan')
block = text[i:i+400]
assert block.index('init_db') < block.index('run_instance_bootstrap'), 'init_db must run before bootstrap'
"

echo "All deploy checks passed."
