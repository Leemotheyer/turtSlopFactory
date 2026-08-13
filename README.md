# turtSlopFactory

A self-hosted **agentic software factory**: you give it a project specification, and orchestrated AI agents turn it into a Git repository, Docker image, tested deployment, and eventually a production service — with you as supervisor, not micromanager.

## Architecture

```
Dashboard (Next.js)  →  Control Plane (FastAPI)  →  Orchestrator  →  Agent Workers
                              ↓
                        PostgreSQL + Redis
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design: state machine, agent roles, sandbox isolation, testing gates, and deployment pipeline.

## Quick start

### With Docker Compose

```bash
docker compose up --build
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### Local development

**Backend:**

```bash
cd orchestrator
pip install -e ".[dev]"
# Start Postgres + Redis (or use docker compose up postgres redis)
uvicorn app.main:app --reload --port 8000
```

**Dashboard:**

```bash
cd dashboard
npm install
npm run dev
```

## What works today (Phase 1)

- Project CRUD with state machine transitions
- Task queue API
- Event persistence + WebSocket live stream
- Dashboard: project list, pipeline view, live events

## What's next

| Phase | Focus |
|-------|-------|
| 2 | ARQ task queue, orchestrator executor, `LocalAgentRunner` |
| 3 | Sandboxed workspaces, build runner, tool gateway |
| 4 | Cursor/CLI agent integration, Architect → Developer → Tester pipeline |
| 5 | Contract tests, container smoke, staging deploy |
| 6 | Auth, reviewer agent, production approval gates |

## Core concepts

1. **State machine, not free-form agents** — projects move through explicit gates (planning → implement → test → docker → staging → production).
2. **Role-based agents** — architect plans, developer codes, tester validates, reviewer judges.
3. **Git as memory** — every change is a commit on a task branch.
4. **Testing as gates** — nothing deploys without passing unit, integration, container smoke, and contract tests.
5. **AgentRunner abstraction** — Cursor is one backend; swap in Claude Code, OpenAI, or local models.

## License

MIT
