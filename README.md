# turtSlopFactory

A self-hosted **agentic software factory**: give it a project specification, and orchestrated AI agents plan, implement, test, Docker-build, deploy to staging, and promote to production — with you as supervisor.

## Quick start

**One command, no `.env` file:**

```bash
docker compose up -d
# open http://localhost:8044
```

Or use the install script:

```bash
curl -fsSL https://raw.githubusercontent.com/Leemotheyer/turtSlopFactory/main/install.sh | bash
```

| URL | Purpose |
|-----|---------|
| http://localhost:8044 | Dashboard + API (single port via gateway) |
| http://localhost:9010–9039 | Live project previews |

Everything else — encryption key, hostname, Cursor, API key — is auto-configured or set in the dashboard.

## What runs

| Container | Role |
|-----------|------|
| **gateway** (Caddy) | Serves dashboard + proxies `/api` and `/ws` on port 8044 |
| **factory** | API + pipeline worker in one container (Docker socket for builds) |
| **dashboard** | Next.js UI |
| **postgres** / **redis** | Internal data stores |

**4 app containers** instead of 5 — no separate worker service.

## Portainer

Paste [`portainer-stack.yml`](portainer-stack.yml) into **Stacks → Web editor**. No bind mounts, no env vars. Open `http://<server-ip>`.

See [docs/PORTAINER.md](docs/PORTAINER.md).

## Build from source

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
# or: make dev
```

## After deploy

1. Open the dashboard — hostname is **auto-detected** when not on localhost
2. Optional: **Cursor** menu → connect API key, choose agent backend
3. Optional: set a **factory API key** under Cursor → Deployment
4. Create a project and **Start pipeline**

## Auto-configured

| Setting | How |
|---------|-----|
| Encryption key | Generated on first boot, saved on workspace volume |
| API + dashboard URL | Single origin on port 80 (gateway) |
| Preview hostname | Auto-detected from your browser / `X-Forwarded-Host` |
| Database / Redis | Internal compose defaults |
| CORS | Open for self-hosted |

## Optional env overrides

```env
HTTP_PORT=8044      # default; change if 8044 is taken
IMAGE_TAG=latest    # pin GHCR release
PUBLIC_HOST=factory.example.com
```

## Local development

```bash
cd orchestrator && pip install -e ".[dev,cursor]"
docker compose up postgres redis -d
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal, only for non-combined dev)
WORKER_ENABLED=false python worker_main.py

cd dashboard && npm install && npm run dev
```

## Generated apps

Each project includes `docker-compose.yml`:

```bash
cd project/repo && docker compose up -d --build
```

## License

MIT
