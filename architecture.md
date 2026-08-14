# turtSlopFactory — Architecture

## System context

turtSlopFactory is a **self-hosted agentic software factory**. The user interacts through a browser dashboard. A FastAPI **control plane** orchestrates AI agents, persists state in **PostgreSQL**, queues work through **Redis**, and builds/deploys generated applications via the host **Docker** socket.

```
┌──────────────────────────────────────────────────────────────────┐
│                         User (browser)                            │
│              check in periodically — no pair programming        │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS (port 8044)
┌────────────────────────────▼─────────────────────────────────────┐
│  Caddy gateway                                                    │
│  ├── /           → Next.js dashboard (static + SSR)              │
│  ├── /api/*      → FastAPI control plane                         │
│  └── /ws/events  → WebSocket event stream                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   PostgreSQL             Redis              Pipeline worker
   (projects,             (queue,             (state machine +
    tasks, events)          pub/sub)            agent executor)
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
              Agent runners (Cursor / local shell)
                             │
                             ▼
              Workspace (git repo + Docker build)
                             │
                             ▼
              Generated app (Python 3.12 + FastAPI :8080)
```

---

## Technology stack

### Factory platform

| Layer | Technology | Version / notes |
|-------|------------|-----------------|
| Language | Python | 3.12 (orchestrator) |
| API framework | FastAPI | Async, OpenAPI auto-docs |
| ASGI server | Uvicorn | Embedded in container |
| Dashboard | Next.js + TypeScript | App Router, client components |
| Database | PostgreSQL | Embedded in single-container deploy |
| Queue / pub-sub | Redis | Task queue + WebSocket fan-out |
| Reverse proxy | Caddy | Single origin for UI + API + WS |
| Container | Docker | Single `factory` service + socket mount |
| Testing | pytest + pytest-asyncio | Orchestrator unit/integration tests |
| Packaging | Hatchling (`pyproject.toml`) | `orchestrator/` package |

### Generated applications (mandatory template)

| Layer | Technology | Notes |
|-------|------------|-------|
| Language | **Python 3.12** | `python:3.12-slim` base image |
| API | **FastAPI** | REST + static web UI |
| Server | Uvicorn | `--host 0.0.0.0 --port 8080` |
| Port | **8080** | EXPOSE and compose mapping |
| Health | **`GET /health`** | JSON `{"status": "ok", "service": "<slug>"}` |
| Tests | **pytest** + FastAPI TestClient | Unit + integration modules |
| Container | Dockerfile + docker-compose.yml | HTTP healthcheck on `/health` |
| Contract | `project.contract.yaml` | Acceptance gates for tester agent |

The scaffolder (`orchestrator/app/workspace/scaffolder.py`) encodes this template for every new project.

---

## Deployment topology

### Single-container factory

```yaml
# docker-compose.yml (simplified)
services:
  factory:
    image: ghcr.io/leemotheyer/turtslopfactory:latest
    ports:
      - "8044:80"          # dashboard + API
      - "9010-9039:9010-9039"  # project previews
    volumes:
      - ${FACTORY_DATA:-./data}:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

Internal supervisord processes: PostgreSQL, Redis, Uvicorn (API + worker), Next.js, Caddy.

Persistent layout:

```
${FACTORY_DATA}/
  config/         # encryption key, optional local.env
  workspaces/     # per-project git repos, logs, artifacts
  postgres/       # database files
  redis/          # queue persistence
```

### Generated app deploy

```bash
cd workspaces/{project_id}/repo
docker compose up -d --build
# → http://localhost:8080
# → GET http://localhost:8080/health
```

---

## Control plane API design

Base URL: `/api` (proxied through Caddy). Unauthenticated by default; optional `X-Factory-Api-Key` middleware.

### Health & real-time

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness — `{"status": "ok", "version": "1.0.0"}` |
| `WS` | `/ws/events` | Stream `FactoryEvent` JSON (agent output, state changes, pings) |

### Projects & tasks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create project `{name, description, repo_url?, branch?}` |
| `GET` | `/api/projects/{id}` | Project detail |
| `PATCH` | `/api/projects/{id}` | Update repo/branch settings |
| `POST` | `/api/projects/{id}/advance` | Manual state advance (supervisor) |
| `POST` | `/api/projects/{id}/fail` | Mark gate failure → diagnosing |
| `GET` | `/api/projects/{id}/tasks` | List tasks |
| `POST` | `/api/projects/{id}/tasks` | Enqueue task `{title, description, role}` |

### Pipeline & deployments

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pipeline/{id}/detail` | Full project detail (metadata, URLs, state) |
| `POST` | `/api/pipeline/{id}/run` | Start or resume autonomous pipeline |
| `POST` | `/api/pipeline/{id}/promote` | Promote staging → production |
| `POST` | `/api/pipeline/{id}/merge-to-main` | Merge work branch after approval |
| `GET` | `/api/pipeline/{id}/deployments` | Deployment history |
| `GET` | `/api/pipeline/{id}/artifacts/{name}` | Download artifact |
| `GET` | `/api/pipeline/{id}/logs/{name}` | Fetch agent/build log |

### Discovery & feedback

| Method | Path | Description |
|--------|------|-------------|
| `GET/POST` | `/api/projects/{id}/discovery` | Discovery session CRUD |
| `POST` | `/api/projects/{id}/discovery/submit` | Submit intake answers |
| `GET` | `/api/projects/{id}/progress` | Progress digest for async check-in |
| `GET/POST` | `/api/projects/{id}/notes` | Supervisor/agent notes |
| `GET` | `/api/projects/{id}/input-requests` | Pending agent questions |
| `POST` | `/api/projects/{id}/input-requests/{rid}/respond` | Answer or dismiss |

### Integrations & settings

| Method | Path | Description |
|--------|------|-------------|
| `GET/POST/DELETE` | `/api/cursor/*` | Cursor API connection, models, usage |
| `GET/POST/DELETE` | `/api/github/*` | GitHub token connection |
| `GET/PUT` | `/api/settings/*` | Factory setup, agent backend, preview host, API key |
| `GET/POST/DELETE` | `/api/projects/{id}/secrets` | Encrypted project secrets |
| `GET` | `/api/events` | Historical events (paginated) |
| `GET` | `/api/notifications` | User notifications + unread count |

### Generated app API (template)

Every scaffolded project exposes at minimum:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/api/info` | App name and description |
| `GET/POST` | `/api/items` | Example CRUD resource |
| `GET` | `/` | Static web UI (when `app/static/` exists) |

Feature modules auto-register via `app/features/*.py` routers.

---

## Pipeline state machine

```
REQUESTED → DISCOVERY → INTAKE_PENDING → PLANNING → IMPLEMENTING
    → UNIT_TESTING → INTEGRATION_TESTING → DOCKER_BUILD
    → STAGING_DEPLOY → SMOKE_TESTING → REVIEW → PRODUCTION
```

Failure at any gate:

```
<any gate> → DIAGNOSING → FIXING → (re-enter failed gate)
```

After `max_attempts` (default 5): `AUTONOMOUSLY_BLOCKED` — requires supervisor action.

### Agent roles per stage

| Stage | Primary agent | Output |
|-------|---------------|--------|
| DISCOVERY / INTAKE | Discovery | Refined spec, intake form answers |
| PLANNING | Architect | `requirements.md`, `architecture.md`, contract |
| IMPLEMENTING | Developer | Code, commits, tests |
| UNIT/INTEGRATION/SMOKE | Tester | Structured test report |
| REVIEW | Reviewer | Approve/reject checklist |
| DOCKER_BUILD / DEPLOY | Developer + orchestrator | Image tag, preview URL |

---

## Agent architecture

### AgentRunner abstraction

Agents are decoupled from any single LLM vendor:

```python
class AgentRunner(Protocol):
    async def start(self, task: Task, role: AgentRole) -> AgentRun: ...
    async def send(self, run_id: str, message: str) -> None: ...
    async def pause(self, run_id: str) -> None: ...
    async def stop(self, run_id: str) -> None: ...
    async def stream_events(self, run_id: str) -> AsyncIterator[AgentEvent]: ...
```

Implementations: `CursorCloudRunner`, `CursorLocalRunner`, `LocalAgentRunner`.

### Tool permissions (summary)

| Capability | Architect | Developer | Tester | Reviewer |
|------------|-----------|-----------|--------|----------|
| Write docs | ✓ | — | — | — |
| Write code | — | ✓ | — | — |
| Run tests / probes | — | ✓ | ✓ | — |
| Docker build | — | via proxy | — | — |
| Deploy production | — | — | — | orchestrator only |

### Workspace layout

```
/data/workspaces/{project_id}/
  repo/                 # git checkout (work branch)
  metadata.json         # preview_url, staging_url, ports
  logs/
  artifacts/
    requirements.md
    architecture.md
    discovery-plan.md
```

Git branching: isolated `factory/{slug}-{hash}` work branches merge to `main` only after gates pass.

---

## Event model

All significant actions emit `FactoryEvent` records (PostgreSQL + Redis pub/sub + WebSocket):

```json
{
  "type": "state.transition",
  "project_id": "uuid",
  "task_id": "uuid",
  "payload": {"from": "IMPLEMENTING", "to": "UNIT_TESTING"}
}
```

Event types include: `agent.command.*`, `test.completed`, `task.status.changed`, `deployment.*`, `progress.updated`, `input.requested`, `discovery.*`, `notification.created`.

---

## Testing strategy

### Factory (orchestrator)

| Layer | Tool | Scope |
|-------|------|-------|
| Unit | pytest | State machine, scaffolder, git branching, secrets crypto, work planner |
| Integration | pytest-asyncio | API routes with in-memory/SQLite DB, mocked runners |
| Contract | pytest + httpx | Cursor/GitHub client response parsing |
| Deploy smoke | `deploy/healthcheck.sh` | Container `GET /health` after boot |

Run locally:

```bash
cd orchestrator
pip install -e ".[dev,cursor]"
pytest tests/ -v --tb=short
```

CI should enforce pytest pass before image publish.

### Generated applications

| Gate | Command / check | Pass criteria |
|------|-----------------|---------------|
| Unit | `pytest tests/test_app.py -v` | All tests green; `/health` covered |
| Integration | `pytest tests/test_integration.py -v` | CRUD workflows pass |
| Coverage | `pytest --cov=app --cov-report=term-missing` | Critical routes covered (health, core API) |
| Container smoke | `docker compose up -d --build` | Healthcheck hits `http://localhost:8080/health` → 200 |
| Contract | Parse `project.contract.yaml` | Each requirement ID mapped to a test or probe |

Example health test (generated template):

```python
def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

### Pipeline-enforced gates

The `PipelineExecutor` runs gates in order:

1. **pytest** (unit + integration) in workspace
2. **`docker build`** via host socket
3. **Staging deploy** on allocated preview port
4. **HTTP smoke** — `GET /health` on deployed container
5. **Reviewer** — requirements checklist vs. diff + test report

On failure, structured fix prompt includes requirement ID, logs, and instruction not to weaken tests.

---

## Security architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Browser   │────▶│ Caddy :80    │────▶│ FastAPI         │
│  (trusted)  │     │ (+ optional  │     │ + API key MW    │
└─────────────┘     │  API key)    │     └────────┬────────┘
                    └──────────────┘              │
                                                  ▼
                                        ┌─────────────────┐
                                        │ Agent sandbox   │
                                        │ (no docker.sock)│
                                        └────────┬────────┘
                                                 │ RPC
                                                 ▼
                                        ┌─────────────────┐
                                        │ Build runner    │
                                        │ (docker.sock)   │
                                        └─────────────────┘
```

- Secrets encrypted with instance key (`FACTORY_DATA/config/`).
- Staging and production use separate env namespaces.
- Agents never receive unrestricted shell on the host.

---

## Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Single container | Postgres + Redis + API + UI bundled | Minimize home-lab operational burden |
| No auth by default | Trusted LAN | Matches single-user intake spec |
| Git work branches | Isolated `factory/*` branches | Safe autonomous iteration |
| FastAPI for generated apps | Python 3.12 + pytest ecosystem | Strong agent tooling, simple Docker story |
| Port 8080 for generated apps | Convention in scaffolder | Predictable health checks and compose |
| Event-sourced UI | WebSocket + Postgres events | Async users can replay what happened while away |
| Pluggable AgentRunner | Cursor + local backends | Avoid vendor lock-in |

---

## Implementation map (repository)

| Path | Responsibility |
|------|----------------|
| `orchestrator/app/main.py` | FastAPI app, `/health`, WebSocket, router mount |
| `orchestrator/app/pipeline/executor.py` | State machine + agent orchestration |
| `orchestrator/app/agents/` | Agent runners and prompt builders |
| `orchestrator/app/workspace/` | Provisioner, scaffolder, workspace manager |
| `orchestrator/app/api/` | REST route modules |
| `orchestrator/tests/` | pytest suite |
| `dashboard/src/` | Next.js UI |
| `deploy/` | Caddy, supervisord, healthcheck scripts |
| `docker-compose.yml` | Production single-container deploy |

---

## Future considerations (post-v1)

- OIDC authentication and RBAC for shared homelab teams
- Temporal or ARQ upgrade for durable workflow scheduling
- Firecracker microVM sandboxes for stronger agent isolation
- Playwright E2E gate for generated apps with complex frontends
- Prometheus metrics and alerting hooks
