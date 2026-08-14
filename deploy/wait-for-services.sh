#!/usr/bin/env bash
set -euo pipefail

for _ in $(seq 1 60); do
  if pg_isready -h 127.0.0.1 -U factory -d factory >/dev/null 2>&1 && redis-cli -h 127.0.0.1 ping 2>/dev/null | grep -q PONG; then
    exec "$@"
  fi
  sleep 1
done

echo "Timed out waiting for postgres/redis" >&2
exit 1
