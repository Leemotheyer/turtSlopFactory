# turtSlopFactory — Architecture

## System context

turtSlopFactory is an **agentic software factory**: a control plane that orchestrates AI agents to build Docker-deployable web applications. The factory runs as a single self-contained container; each **project** it creates is an independent Python/FastAPI app with its own repository, tests, and Docker image.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         User (home-lab browser)                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTPS :8044
┌───────────────────────────────▼──────────────────────────────────────┐
│                    turtSlopFactory (single container)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────┐  ┌───────────────┐  │
│  │ Caddy :80   │→ │ Next.js UI   │  │ FastAPI │  │ Pipeline      │  │
│  │  gateway    │  │  dashboard   │  │  :8000  │  │ worker        │  │
│  └─────────────┘  └──────────────┘  └────┬────┘  └───────┬───────┘  │
│                                           │                │          │
│                    ┌──────────────────────┼────────────────┘          │
│                    ▼                      ▼                           │
│              PostgreSQL              Redis queue                      │
│              (projects, events)      (tasks, pub/sub)                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ docker build / preview
┌───────────────────────────────▼──────────────────────────────────────┐
│              Generated project (per workspace)                        │
│   Python 3.12 + FastAPI · Web UI · Docker :8080 · pytest · /health   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Technology stack

### Factory (control plane)

| Layer | Technology | Version / notes |
|-------|------------|-----------------|
| Language | Python | 3.12 |
| API framework | FastAPI | Async, OpenAPI at `/docs` |
| ASGI server | Uvicorn | Embedded in supervisord |
| Dashboard | Next.js + TypeScript | Standalone build, SSR-capable |
| Gateway | Caddy 2.x | Reverse proxy: UI, `/api`, `/ws`, `/preview` |
| Database | PostgreSQL | Embedded; async via SQLAlchemy + asyncpg |
| Queue / pub-sub | Redis | Task queue, WebSocket fan-out |
| Process manager | Supervisord | API, worker, dashboard, postgres, redis, caddy |
| Container | Docker | Single image; host socket for project builds |
| Testing | pytest + pytest-asyncio | Orchestrator test suite |

**External port:** host `8044` → container `80` (Caddy).  
**Health endpoint:** `GET /health` → `{"status": "ok", "version": "1.0.0"}`.

### Generated applications (factory output standard)

| Layer | Technology | Notes |
|-------|------------|-------|
| Language | Python | 3.12 |
| API framework | FastAPI | REST + static web UI |
| Server | Uvicorn | `--host 0.0.0.0 --port 8080` |
| Container | Docker | `EXPOSE 8080`, compose healthcheck on `/health` |
| Testing | pytest + httpx TestClient | Unit + integration; coverage in gates |
| Contract | `project.contract.yaml` | Requirements IDs, healthcheck, gate config |

---

## Component architecture

### 1. Gateway (Caddy)

Routes on port 80 inside the container:

| Path prefix | Backend | Purpose |
|-------------|---------|---------|
| `/preview/*` | FastAPI :8000 | Live project preview proxy |
| `/api/*`, `/health`, `/docs`, `/ws/*` | FastAPI :8000 | Control plane API + WebSocket |
| `/` (default) | Next.js :3000 | Dashboard UI |

Proxy headers (`X-Forwarded-Host`, etc.) enable auto-detection of public hostname for preview URLs.

### 2. Control plane (FastAPI)

**Entry:** `orchestrator/app/main.py`

Responsibilities:

- REST API for projects, tasks, pipeline, discovery, secrets, settings
- WebSocket event stream at `/ws/events`
- Preview reverse proxy for in-progress apps
- Lifespan hooks: DB init, bootstrap, Redis connect, pipeline worker

**Middleware:**

- Optional API key enforcement on mutating routes
- CORS (open for self-hosted default)

### 3. Pipeline worker

**Entry:** `orchestrator/app/worker.py` (also runs in-process when `WORKER_ENABLED=true`)

Executes the project state machine via `PipelineExecutor`:

```
REQUESTED → DISCOVERY → INTAKE_PENDING → PLANNING → IMPLEMENTING
  → UNIT_TESTING → INTEGRATION_TESTING → DOCKER_BUILD → STAGING_DEPLOY
  → SMOKE_TESTING → REVIEW → PRODUCTION
```

Failure path at any gate:

```
<any gate> → DIAGNOSING → FIXING → (re-enter failed gate)
         → AUTONOMOUSLY_BLOCKED (after max attempts)
```

### 4. Agent runners

Abstracted via `AgentRunner` protocol; factory implementation routes by role:

| Role | Backend | Capabilities |
|------|---------|--------------|
| discovery, architect, developer, reviewer | Cursor Cloud / Cursor local / local scaffold | LLM-driven planning and coding |
| tester, docker, preview | Local runner | Deterministic test/build/preview commands |

Tool permissions enforce separation: architects write docs only; testers cannot modify source; production deploy is orchestrator-only.

### 5. Workspace manager

Per-project isolated directories under `WORKSPACE_ROOT`:

```
/data/workspaces/{project_id}/
  repo/                 # git checkout (feature branch)
  artifacts/            # requirements.md, architecture.md, discovery-plan.md
  logs/                 # pipeline.log, agent output
  metadata.json         # failed_gate, preview port, image tag
```

Scaffolder (`app/workspace/scaffolder.py`) seeds generated apps with the standard Python 3.12/FastAPI/Docker-8080 template.

### 6. Dashboard (Next.js)

Single-page application (`dashboard/src/app/page.tsx`) consuming the REST API and WebSocket. Key views:

- Project list with pipeline stepper
- Live event feed and progress digest
- Discovery/intake form (optional, auto-submit supported)
- Cursor/GitHub/settings panels
- Artifact viewer, log tail, preview link
- Notifications for async user actions (secrets, env vars)

Mobile-first CSS modules; responsive layout for phone check-ins.

---

## Data model

PostgreSQL tables (SQLAlchemy models in `app/db_models.py`):

| Entity | Key fields |
|--------|------------|
| **projects** | id, name, description, state, branch, work_branch, image_tag |
| **tasks** | id, project_id, role, status, attempt, max_attempts |
| **events** | id, project_id, type, payload, created_at |
| **discovery_sessions** | project_id, form_fields, responses, status, expires_at |
| **project_secrets** | project_id, key_name, encrypted_value |
| **notifications** | project_id, type, title, message, read |
| **deployments** | project_id, environment, image_tag, url, status |
| **input_requests** | project_id, question, status, response |
| **progress_entries** | project_id, summary, percent |

Events are append-only for audit and WebSocket replay.

---

## API design

Base URL: `http://<host>:8044` (same origin as dashboard).

### Health and real-time

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `WS` | `/ws/events` | Live factory events (ping every 30s) |

### Projects (`/api/projects`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create project |
| `GET` | `/api/projects/{id}` | Get project |
| `PATCH` | `/api/projects/{id}` | Update repo/branch settings |
| `DELETE` | `/api/projects/{id}` | Delete project |
| `POST` | `/api/projects/{id}/advance` | Manual state advance (debug/admin) |
| `POST` | `/api/projects/{id}/fail` | Manual fail transition |
| `GET/POST` | `/api/projects/{id}/tasks` | List/create tasks |

### Pipeline (`/api/pipeline`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/pipeline/{id}/detail` | Full project detail (tasks, events, notes) |
| `POST` | `/api/pipeline/{id}/run` | Start or resume pipeline |
| `POST` | `/api/pipeline/{id}/promote` | Promote to production |
| `POST` | `/api/pipeline/{id}/merge-to-main` | Merge feature branch |
| `GET` | `/api/pipeline/{id}/artifacts/{name}` | Download artifact file |
| `GET` | `/api/pipeline/{id}/logs/{name}` | Tail log file |
| `GET` | `/api/pipeline/{id}/deployments` | Deployment history |

### Discovery (`/api/projects`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects/{id}/discovery` | Get discovery session |
| `POST` | `/api/projects/{id}/discovery` | Start discovery |
| `POST` | `/api/projects/{id}/discovery/submit` | Submit intake responses |

### Feedback and progress (`/api/projects`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects/{id}/progress` | Progress digest |
| `GET/POST` | `/api/projects/{id}/notes` | Agent/user notes |
| `GET` | `/api/projects/{id}/input-requests` | Pending questions |
| `POST` | `/api/projects/{id}/input-requests/{rid}/respond` | Answer question |

### Supporting APIs

| Prefix | Purpose |
|--------|---------|
| `/api/tasks` | Global task list and status updates |
| `/api/events` | Historical event query |
| `/api/notifications` | User notifications |
| `/api/projects/{id}/secrets` | Encrypted project secrets |
| `/api/cursor/*` | Cursor connection, models, usage |
| `/api/github/*` | GitHub token management |
| `/api/settings/*` | Factory config, API key, agent backend |

### Generated app API (standard template)

Each factory-built app exposes at minimum:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | `{"status": "ok", "service": "<slug>"}` |
| `GET` | `/api/info` | App name and description |
| `GET/POST` | `/api/items` | Example CRUD (extended by developer agent) |
| `GET` | `/` | Web UI (static files) |

---

## Agent pipeline flow

```
User creates project
        │
        ▼
┌───────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Discovery    │────▶│ Intake form  │────▶│ Auto-submit if  │
│  (loose plan) │     │ (optional)   │     │ user absent     │
└───────────────┘     └──────────────┘     └────────┬────────┘
                                                      │
        ┌─────────────────────────────────────────────▼
        │
        ▼
┌───────────────┐     writes requirements.md, architecture.md
│  Architect    │──── project.contract.yaml, API/DB schema
└───────┬───────┘
        ▼
┌───────────────┐     implements features, commits, pytest
│  Developer    │──── proposes improvements, iterates
└───────┬───────┘
        ▼
┌───────────────┐     unit → integration → smoke
│  Tester       │──── docker healthcheck :8080/health
└───────┬───────┘
        │ pass
        ▼
┌───────────────┐     docker build, staging preview
│  Build/Deploy │
└───────┬───────┘
        ▼
┌───────────────┐     requirement checklist
│  Reviewer     │──── approve / reject → fix loop
└───────┬───────┘
        ▼
   PRODUCTION (user can `docker compose up` in project repo)
```

On test failure, orchestrator packages logs, exit codes, and requirement IDs into a structured fix prompt for the developer (max 5 attempts).

---

## Testing strategy

### Factory (orchestrator)

**Framework:** pytest with pytest-asyncio for async handlers and services.

**Run:**

```bash
cd orchestrator && python3 -m pytest tests/ -q
# or: make test
```

**Coverage areas** (existing test modules):

| Area | Test module | What is verified |
|------|-------------|------------------|
| State machine | `test_state_machine.py` | Forward/fail transitions, gate indexing |
| Pipeline gates | `test_pipeline_gates.py` | End-to-end gate sequencing |
| Agents | `test_agents.py`, `test_agent_backends.py` | Role routing, local runner |
| Discovery | `test_discovery.py` | Intake generation, auto-submit |
| Git branching | `test_git_branching.py` | Isolated feature branches |
| Preview | `test_preview.py` | URL allocation, proxy |
| Secrets | `test_secrets.py` | Encryption round-trip |
| Worker | `test_worker.py` | Queue processing |
| Project lifecycle | `test_project_lifecycle.py` | CRUD, state persistence |

**CI recommendation:** run pytest on every PR; add `--cov=app --cov-report=term-missing` once baseline coverage is established.

**Integration testing:** `scripts/verify-deploy.sh` smoke-tests a running container (`/health`, dashboard reachability).

### Generated applications (per-project gates)

Defined in `project.contract.yaml` and enforced by the tester agent:

| Gate | Command / check | Pass criteria |
|------|-----------------|---------------|
| **Unit** | `pytest tests/ -q --ignore=tests/test_integration.py` | All tests pass |
| **Integration** | `pytest tests/test_integration.py -q` | CRUD workflows pass |
| **Docker build** | `docker compose build` | Image builds without error |
| **Smoke** | `docker compose up -d` + healthcheck | `GET http://localhost:8080/health` → 200 |
| **Coverage** | `pytest --cov=app --cov-fail-under=70` | Minimum 70% line coverage (configurable) |

Smoke healthcheck (generated `docker-compose.yml`):

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
  interval: 5s
  timeout: 5s
  retries: 5
```

Fix prompts explicitly instruct developers: **do not modify tests to make them pass**.

---

## Deployment topology

### Factory deploy

```bash
docker compose up -d          # default :8044
# or
make dev                      # build from source
```

**Volumes:**

- `${FACTORY_DATA:-./data}:/data` — postgres, redis, workspaces, config
- `/var/run/docker.sock` — build generated project images

**Environment (key vars):**

| Variable | Default | Purpose |
|----------|---------|---------|
| `FACTORY_DATA` | `/data` | Persistent state root |
| `DATABASE_URL` | `postgresql+asyncpg://factory:factory@127.0.0.1:5432/factory` | PostgreSQL |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Queue/pub-sub |
| `WORKER_ENABLED` | `true` | In-process pipeline worker |
| `HTTP_PORT` | `8044` | Host port mapping |

### Generated project deploy

```bash
cd workspaces/{project_id}/repo
docker compose up -d --build   # exposes :8080
curl http://localhost:8080/health
```

---

## Security model (v1)

- **No end-user auth** — factory trusted on home network
- **Optional API key** — protects mutating API routes when enabled
- **Secrets** — Fernet-encrypted in PostgreSQL; injected at agent runtime
- **Agent isolation** — workspaces are per-project; no cross-project file access
- **Build privilege** — only the orchestrator/build runner uses Docker socket
- **Staging vs production** — separate deployment records; human promote gate

---

## Extension points

| Extension | Mechanism |
|-----------|-----------|
| New agent backend | Implement `AgentRunner`; register in `agents/factory.py` |
| Custom test gates | Extend `project.contract.yaml` schema + tester runner |
| External postgres/redis | Override `DATABASE_URL` / `REDIS_URL` env vars |
| Auth/RBAC | Middleware + user table (Phase 6 in roadmap) |
| Temporal workflow engine | Replace Redis queue with durable workflows |

---

## Key file map

| Path | Role |
|------|------|
| `orchestrator/app/main.py` | FastAPI app, `/health`, router mount |
| `orchestrator/app/pipeline/executor.py` | Pipeline state machine executor |
| `orchestrator/app/state_machine.py` | Gate transitions |
| `orchestrator/app/agents/` | Agent runners and prompts |
| `orchestrator/app/workspace/scaffolder.py` | Generated app template (8080, /health) |
| `orchestrator/tests/` | pytest suite |
| `dashboard/src/` | Next.js UI |
| `deploy/Caddyfile` | Gateway routing |
| `Dockerfile` | All-in-one factory image (Python 3.12) |
| `docker-compose.yml` | Production compose (port 8044) |
