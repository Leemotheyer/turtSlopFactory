# turtSlopFactory

A self-hosted **agentic software factory**: give it a project specification, and orchestrated AI agents plan, implement, test, Docker-build, deploy to staging, and promote to production — with you as supervisor.

```
┌─────────────┐     REST + WebSocket     ┌──────────────┐     Redis Queue     ┌────────────┐
│  Dashboard  │ ◄──────────────────────► │ Orchestrator │ ◄──────────────────► │   Worker   │
│  (Next.js)  │                          │  (FastAPI)   │                      │  (Pipeline)│
└─────────────┘                          └──────┬───────┘                      └─────┬──────┘
                                                │                                    │
                                          PostgreSQL                          Docker builds
                                                                                + staging deploy
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

## Usage

1. Open the dashboard and create a project with a natural-language spec
2. Click **Start pipeline** — agents will automatically:
   - **Architect** — write requirements and architecture docs
   - **Developer** — scaffold a FastAPI web app with Docker
   - **Tester** — run unit, integration, and smoke tests
   - **Build** — create a Docker image
   - **Deploy** — run staging container
   - **Reviewer** — validate against acceptance criteria
3. When state reaches **REVIEW**, click **Promote to production**
4. Open the staging/production URL to interact with the generated app

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

### Agent roles

| Role | Responsibility |
|------|---------------|
| Architect | Requirements, architecture, acceptance contract |
| Developer | Code generation, Git commits |
| Tester | Unit, integration, smoke tests |
| Reviewer | Approve/reject against checklist |

### Pipeline states

```
REQUESTED → PLANNING → IMPLEMENTING → UNIT_TESTING → INTEGRATION_TESTING
  → DOCKER_BUILD → STAGING_DEPLOY → SMOKE_TESTING → REVIEW → [human] → PRODUCTION
```

## Production deployment

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD and API_KEY
docker compose up -d --build
```

Set `API_KEY` in `.env` to require the `X-API-Key` header on API requests.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | `factory` | Database password |
| `API_KEY` | (empty) | API authentication key |
| `API_PORT` | `8000` | Orchestrator port |
| `DASHBOARD_PORT` | `3000` | Dashboard port |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Dashboard → API URL |

## Local development

**Orchestrator:**
```bash
cd orchestrator
pip install -e ".[dev]"
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

## Extending with real LLM agents

The `LocalAgentRunner` scaffolds apps deterministically (no API key needed). To plug in Cursor, Claude, or OpenAI:

1. Implement `AgentRunner` in `orchestrator/app/agents/`
2. Register it in the pipeline executor
3. Set `AGENT_BACKEND=cursor` (or similar) in env

```python
class AgentRunner(Protocol):
    async def run(self, role, project_id, task_id, workspace, context) -> AgentRun: ...
```

## Project structure

```
├── dashboard/          # Next.js control plane UI
├── orchestrator/       # FastAPI API + pipeline worker
│   └── app/
│       ├── agents/     # Agent runners (local, future: cursor)
│       ├── pipeline/   # State machine executor
│       ├── workspace/  # Sandbox + scaffolder
│       └── api/        # REST endpoints
├── docs/               # Architecture documentation
└── docker-compose.yml  # Full stack
```

## License

MIT
