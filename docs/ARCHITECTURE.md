# turtSlopFactory — Agentic Software Factory

A self-hosted platform that turns project specifications into tested, Docker-deployable applications using orchestrated AI agents.

## Design principle

The dashboard does **not** control Cursor directly. It is the **control plane** for a software factory where agents are workers inside isolated sandboxes. Cursor (or any LLM runtime) is one possible `AgentRunner` backend.

## Your use case: server-side Docker apps (no browser UI)

Most factory examples assume web apps with Playwright E2E. Your projects are different: background services, workers, APIs without UI, cron jobs, queue consumers.

Adapt the testing pipeline accordingly:

| Gate | What it validates |
|------|-------------------|
| Unit tests | Business logic in isolation |
| Integration tests | DB, queues, external mocks |
| Container smoke | `docker compose up`, healthcheck passes |
| Contract tests | OpenAPI/gRPC schemas, CLI `--help` output |
| Runtime probes | `docker exec` CLI commands, log patterns, metrics |
| Staging soak | Deploy to staging, synthetic traffic, log review |

Skip Playwright unless a project explicitly has a web UI.

## System overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Next.js Dashboard                         │
│  Projects · Agents · Tasks · Logs · Diffs · Deployments     │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST + WebSocket (SSE)
┌──────────────────────────▼──────────────────────────────────┐
│                   FastAPI Control Plane                      │
│  Projects API · Task queue · Event bus · WebSocket fan-out  │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   PostgreSQL           Redis            Orchestrator
   (state)           (queue/pubsub)    (state machine)
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Architect    Developer      Tester
              │            │            │
              └────────────┼────────────┘
                           ▼
                  Isolated Workspace
                  (container / VM)
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           Git repo    Docker       Test runner
```

## Project state machine

Every project moves through explicit states. Failures transition to `DIAGNOSING` → `FIXING`, not silent retries.

```
REQUESTED → PLANNING → IMPLEMENTING → UNIT_TESTING → INTEGRATION_TESTING
    → DOCKER_BUILD → STAGING_DEPLOY → SMOKE_TESTING → REVIEW → PRODUCTION
```

On failure at any gate:

```
<any gate> → FAIL → DIAGNOSING → FIXING → (re-enter appropriate test state)
```

Hard cap: `MAX_ATTEMPTS = 5` per task, then `AUTONOMOUSLY_BLOCKED` for human review.

## Agent roles

### Architect
- **Input:** natural-language spec ("self-hosted RSS poller with REST API")
- **Output:** `requirements.md`, `architecture.md`, API schema, DB schema, Docker spec, testing strategy, acceptance criteria
- **Tools:** read/write docs, search — **no** `deploy_production`, **no** arbitrary shell

### Developer
- **Input:** architect artifacts + task description
- **Output:** code, commits on feature branch, unit/integration tests
- **Tools:** filesystem, git, run_command, run_tests, docker_build (via runner proxy)

### Tester
- **Input:** running staging deployment + acceptance contract
- **Output:** structured test report with logs, exit codes, contract violations
- **Tools:** run_command, docker_logs, docker_exec, http_probe, contract_validate — **no** write_file

### Reviewer (judge)
- **Input:** diff, test results, logs, original requirements
- **Output:** approve / reject with per-requirement checklist and severity-rated concerns
- Cannot merge its own work; orchestrator enforces separation

## Workspace isolation

```
/data/projects/{project_id}/
/data/workspaces/{task_id}/
    repo/              # git checkout
    docker-compose.yml
    test-results/
    logs/
    artifacts/
```

Agents run inside ephemeral containers. **Do not** mount the host Docker socket into agent containers. Use a privileged **build runner** service that agents invoke via RPC:

```
Agent → orchestrator → build-runner → docker build/push
```

## Event-driven control plane

Agents emit events; the dashboard subscribes over WebSocket:

```json
{"type": "agent.command.started", "task_id": "8472", "command": "pytest tests/"}
{"type": "agent.command.output",  "task_id": "8472", "output": "143 passed"}
{"type": "test.completed",        "task_id": "8472", "passed": true}
{"type": "state.transition",     "project_id": "abc", "from": "UNIT_TESTING", "to": "INTEGRATION_TESTING"}
```

Store all events in PostgreSQL for replay and audit.

## Git as source of truth

Every agent action that changes code results in a commit on a task branch:

```
main
├── feature/task-8472-auth
└── feature/task-8473-healthcheck
```

Orchestrator merges only after: all gates pass + reviewer approves + (optional) human approval for production.

## Acceptance contract (per project)

```yaml
# project.contract.yaml
application:
  name: invoice-poller
  type: worker  # worker | api | cron | cli

requirements:
  - id: R1
    description: Poll invoices every 5 minutes
  - id: R2
    description: Expose /health on port 8080

deployment:
  healthcheck:
    type: http
    path: /health
    port: 8080
  # or for pure workers:
  # healthcheck:
  #   type: log_pattern
  #   pattern: "ready"
  #   within_seconds: 30

tests:
  unit: true
  integration: true
  contract: true
  smoke: true
  soak_minutes: 5  # optional staging soak

gates:
  max_fix_attempts: 5
  require_reviewer: true
  require_human_for_production: true
```

## AgentRunner abstraction

Decouple from Cursor so you can swap backends:

```python
class AgentRunner(Protocol):
    async def start(self, task: Task, role: AgentRole) -> AgentRun: ...
    async def send(self, run_id: str, message: str) -> None: ...
    async def pause(self, run_id: str) -> None: ...
    async def stop(self, run_id: str) -> None: ...
    async def stream_events(self, run_id: str) -> AsyncIterator[AgentEvent]: ...
```

Implementations: `CursorAgentRunner`, `ClaudeCodeRunner`, `OpenAICodexRunner`.

## Tool permissions by role

| Tool | Architect | Developer | Tester | Reviewer |
|------|-----------|-----------|--------|----------|
| read_file | ✓ | ✓ | ✓ | ✓ |
| write_file | docs only | ✓ | ✗ | ✗ |
| run_command | ✗ | ✓ | ✓ | ✗ |
| git_commit | ✗ | ✓ | ✗ | ✗ |
| docker_build | ✗ | via proxy | ✗ | ✗ |
| docker_logs | ✗ | ✓ | ✓ | ✓ |
| docker_exec | ✗ | ✓ | ✓ | ✗ |
| http_probe | ✗ | ✓ | ✓ | ✗ |
| deploy_staging | ✗ | ✗ | via proxy | ✗ |
| deploy_production | ✗ | ✗ | ✗ | ✗ |

Production deploy is **orchestrator-only**, triggered by dashboard approval.

## Feedback loop

```
Developer implements → Tester runs gates → FAIL
    → Orchestrator packages failure (logs, exit code, diff context)
    → Developer receives structured fix prompt
    → repeat (max 5)
    → PASS → Reviewer → Staging → Production
```

Fix prompts must include: requirement ID, expected vs actual, relevant logs, and **"do not modify tests"**.

## Deployment pipeline

```
Development workspace
    → CI (all gates)
    → Build image → push to registry
    → Deploy staging (internal network)
    → Smoke + soak tests
    → Human approval (dashboard)
    → Deploy production
```

Image tags: `{project}:{build_id}` (e.g. `invoice-poller:build-184`).

## Dashboard screens

1. **Projects** — status, branch, current agent, image tag, staging/prod URLs, history
2. **Agent monitor** — live command output, token usage, files changed, pause/send instruction
3. **Task queue** — queued/running/waiting/blocked tasks
4. **Task detail** — goal, plan, evidence, attempts, diffs, logs, screenshots (if any)
5. **Deployments** — promote, rollback, environment diff

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Dashboard | Next.js + TypeScript | SSR, API routes, good DX |
| Control plane | FastAPI + Python | Agent tooling ecosystem, async |
| Database | PostgreSQL | Projects, tasks, events, deployments |
| Queue | Redis + ARQ (or Temporal later) | Simple start, upgrade path |
| Real-time | WebSocket + Redis pub/sub | Live log streaming |
| Sandboxes | Docker + optional Firecracker | Isolation |
| Registry | Harbor or GHCR | Private images |

## Implementation phases

### Phase 1 — Control plane skeleton (this repo)
- [x] FastAPI with projects/tasks/events API
- [x] WebSocket event stream
- [x] State machine enums and transitions
- [x] Next.js dashboard shell
- [x] docker-compose for local dev (Postgres + Redis)

### Phase 2 — Orchestrator + queue
- Task enqueue/dequeue with ARQ
- State machine executor
- Event persistence and replay
- Basic `LocalAgentRunner` (shell commands for testing)

### Phase 3 — Sandboxed workspaces
- Workspace provisioner (git clone, branch checkout)
- Build runner service (privileged Docker)
- Tool gateway with role-based permissions

### Phase 4 — Agent integration
- `CursorAgentRunner` via Cursor CLI / Cloud Agents API
- Architect → Developer → Tester pipeline
- Structured failure feedback loop

### Phase 5 — Testing harness
- Contract test runner
- Container smoke tests
- `docker exec` probe runner
- Staging deploy + soak

### Phase 6 — Production hardening
- Auth (OIDC), RBAC
- Reviewer agent
- Human approval gates
- Metrics (Prometheus), alerting

## Security notes

- Agents never get raw production credentials
- Staging uses separate secrets namespace
- Build runner is the only privileged Docker component
- All agent commands are logged and attributable
- Rate-limit and budget-cap LLM token usage per project
