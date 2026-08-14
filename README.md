# turtSlopFactory

A self-hosted **agentic software factory**: give it a project specification, and orchestrated AI agents plan, implement, test, Docker-build, deploy to staging, and promote to production — with you as supervisor.

```
┌─────────────┐     REST + WebSocket     ┌──────────────┐     Redis Queue     ┌────────────┐
│  Dashboard  │ ◄──────────────────────► │ Orchestrator │ ◄──────────────────► │   Worker   │
│  (Next.js)  │                          │  (FastAPI)   │                      │  (Pipeline)│
└─────────────┘                          └──────┬───────┘                      └─────┬──────┘
                                                │                                    │
                                          PostgreSQL                          Docker builds
                                                                                + live preview
```

## Quick start

**No `.env` file required.**

```bash
docker compose -f docker-compose.prod.yml up -d
```

Open http://localhost:3000 and complete the one-time setup banner (hostname + optional API key). Connect Cursor from the header menu when you're ready.

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Live previews | http://localhost:8081–8099 (per project) |

### Build from source

```bash
docker compose up -d --build
```

### Portainer

See [docs/PORTAINER.md](docs/PORTAINER.md) — deploy `docker-compose.prod.yml` as a stack with zero environment variables.

## What gets auto-configured

| Setting | How |
|---------|-----|
| Encryption key for secrets | Generated on first boot, stored on the workspace volume |
| Database / Redis | Built into compose with internal credentials |
| API URL for dashboard | Detected from your browser hostname (`:8000`) |
| CORS | Open by default for simple LAN/Portainer deploys |
| Cursor API key | Connect in dashboard after deploy |
| Agent backend | Choose in dashboard (default: Cursor Cloud) |
| Preview hostname | Quick setup banner or Cursor → Deployment |

Optional env overrides (`.env` or Portainer stack env): `PUBLIC_HOST`, `IMAGE_TAG`, `API_KEY`.

## Usage

1. Open the dashboard and create a project with a natural-language spec (optional `repo_url` for GitHub-backed Cursor Cloud agents)
2. Complete discovery intake if prompted
3. Click **Start pipeline**
4. When state reaches **REVIEW**, click **Promote to production**
5. Open the live preview URL to interact with the generated app

## Generated app deployment

Each project includes `Dockerfile` and `docker-compose.yml`:

```bash
cd /path/to/project/repo
docker compose up -d --build
# → http://localhost:8080
```

## Pre-built images (GHCR)

Published on every push to `main`:

| Image | Package |
|-------|---------|
| Orchestrator + worker | `ghcr.io/leemotheyer/turtslopfactory-orchestrator:latest` |
| Dashboard | `ghcr.io/leemotheyer/turtslopfactory-dashboard:latest` |

## Local development

```bash
cd orchestrator && pip install -e ".[dev,cursor]"
docker compose up postgres redis -d
uvicorn app.main:app --reload --port 8000

# Worker (separate terminal)
WORKER_ENABLED=false python worker_main.py

# Dashboard
cd dashboard && npm install && npm run dev
```

## Project structure

```
├── dashboard/              # Next.js control plane UI
├── orchestrator/           # FastAPI API + pipeline worker
├── docker-compose.yml      # Build from source
├── docker-compose.prod.yml # Pre-built images (recommended)
├── docs/PORTAINER.md       # Portainer one-click deploy
└── .github/workflows/      # GHCR image publish
```

## License

MIT
