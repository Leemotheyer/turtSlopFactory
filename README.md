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

## Quick start (build from source)

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Live previews | http://localhost:8081–8099 (per project) |

## Deploy with pre-built images

Images are built automatically on every push to `main` and published to [GitHub Container Registry](https://github.com/Leemotheyer/turtSlopFactory/pkgs/container/turtslopfactory-orchestrator).

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, API_KEY, SECRETS_ENCRYPTION_KEY, CURSOR_API_KEY

docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

| Image | Package |
|-------|---------|
| Orchestrator + worker | `ghcr.io/leemotheyer/turtslopfactory-orchestrator:latest` |
| Dashboard | `ghcr.io/leemotheyer/turtslopfactory-dashboard:latest` |

Pin a release with `IMAGE_TAG=v1.0.0` in `.env` after tagging a release.

### Custom dashboard API URL

The dashboard image is built with `NEXT_PUBLIC_API_URL=http://localhost:8000`. For a custom hostname, either:

- Use `docker compose up --build` (see `docker-compose.yml`), or
- Rebuild only the dashboard with build args:

```bash
docker build -t my-dashboard ./dashboard \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  --build-arg NEXT_PUBLIC_WS_URL=wss://api.example.com
```

## Usage

1. Open the dashboard and create a project with a natural-language spec (optional `repo_url` for GitHub-backed Cursor Cloud agents)
2. Complete discovery intake if prompted
3. Click **Start pipeline** — agents will automatically:
   - **Architect** — write requirements and architecture docs
   - **Developer** — implement backend, frontend, and features (parallel streams)
   - **Tester** — run unit, integration, and smoke tests
   - **Build** — create a Docker image
   - **Deploy** — run live preview container (dev, then production image)
   - **Reviewer** — validate against acceptance criteria
4. When state reaches **REVIEW**, click **Promote to production**
5. Open the live preview or staging/production URL to interact with the generated app

### Cursor agents (default)

The factory defaults to **Cursor Cloud Agents**. Connect your API key in the dashboard **Cursor** panel, or set `CURSOR_API_KEY` in `.env`. Choose the backend:

| Backend | Description |
|---------|-------------|
| `cursor_cloud` | Cursor Cloud Agents (default); uses `repo_url` when set |
| `cursor_local` | Cursor agents on the workspace via `cursor-sdk` |
| `local` | Deterministic scaffold (no API key) |

## Generated app deployment

Each project the factory builds includes a `Dockerfile` and `docker-compose.yml` in its workspace repo. After the pipeline completes, deploy the generated app directly:

```bash
# From the project workspace (default: /data/workspaces/projects/<id>/repo inside the worker)
cd /path/to/project/repo

docker compose up --build -d
# App available at http://localhost:8080
```

Example generated `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 5s
      timeout: 5s
      retries: 5
```

Or build and run the image manually:

```bash
docker build -t my-factory-app .
docker run -d --name my-factory-app -p 8080:8080 my-factory-app
curl http://localhost:8080/health
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

### Agent roles

| Role | Responsibility |
|------|---------------|
| Architect | Requirements, architecture, acceptance contract |
| Developer | Code generation (parallel backend/frontend/feature streams) |
| Tester | Unit, integration, smoke tests |
| Reviewer | Approve/reject against checklist |

### Pipeline states

```
REQUESTED → DISCOVERY → INTAKE_PENDING → PLANNING → IMPLEMENTING → UNIT_TESTING
  → INTEGRATION_TESTING → DOCKER_BUILD → STAGING_DEPLOY → SMOKE_TESTING → REVIEW → PRODUCTION
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | `factory` | Database password |
| `API_KEY` | (empty) | API authentication key (`X-API-Key` header) |
| `API_PORT` | `8000` | Orchestrator port |
| `DASHBOARD_PORT` | `3000` | Dashboard port |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Dashboard → API URL (build-time for dashboard image) |
| `SECRETS_ENCRYPTION_KEY` | (empty) | Fernet key for encrypted project secrets |
| `PREVIEW_HOST` | `localhost` | Hostname in live preview URLs |
| `AGENT_BACKEND` | `cursor_cloud` | `cursor_cloud`, `cursor_local`, or `local` |
| `CURSOR_API_KEY` | (empty) | Cursor API key (or connect via dashboard) |
| `IMAGE_TAG` | `latest` | Image tag for `docker-compose.prod.yml` |

Generate a secrets key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Local development

**Orchestrator:**

```bash
cd orchestrator
pip install -e ".[dev,cursor]"
# Start Postgres + Redis (docker compose up postgres redis -d)
uvicorn app.main:app --reload --port 8000
```

**Worker** (separate terminal):

```bash
cd orchestrator
WORKER_ENABLED=false python worker_main.py
```

**Dashboard:**

```bash
cd dashboard
npm install && npm run dev
```

**Tests:**

```bash
cd orchestrator && python3 -m pytest tests/ -q
```

## CI / container builds

The [docker-publish workflow](.github/workflows/docker-publish.yml) builds and pushes orchestrator and dashboard images to GHCR on every push to `main` and on version tags (`v*`).

## Project structure

```
├── dashboard/              # Next.js control plane UI
├── orchestrator/           # FastAPI API + pipeline worker
│   └── app/
│       ├── agents/         # Factory runner (Cursor cloud/local + scaffold)
│       ├── pipeline/       # State machine executor
│       ├── workspace/      # Sandbox + scaffolder
│       └── api/            # REST endpoints
├── docker-compose.yml      # Full stack (build from source)
├── docker-compose.prod.yml # Full stack (pre-built GHCR images)
├── docs/                   # Architecture documentation
└── .github/workflows/      # CI (Docker image publish)
```

## License

MIT
