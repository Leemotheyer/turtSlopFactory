#!/bin/sh
set -e

# API via Caddy
curl -fsS http://127.0.0.1/health >/dev/null

# Dashboard (direct — catches missing node / failed Next.js startup)
curl -fsS -o /dev/null http://127.0.0.1:3000/
