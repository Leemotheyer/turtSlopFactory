# turtSlopFactory — Requirements

## Overview

**turtSlopFactory** is a self-hosted, agentic software factory for home-lab operators. A user describes a product idea in plain language, starts a project, and walks away. Autonomous development agents discover requirements, plan architecture, implement code, run tests, build Docker images, deploy previews, and iterate until the project reaches a releasable state.

The factory itself is a **full-stack web application** (FastAPI control plane + Next.js dashboard) packaged as a **single Docker container**. Each **generated application** is also a full-stack, Docker-deployable web GUI app built with **Python 3.12 + FastAPI**, exposed on **port 8080**, with **pytest** coverage and a **`/health`** endpoint.

### Primary goal

Enable a home-labber to **start a project and return hours or days later** to a complete, tested, Docker-ready web application — without sitting at the keyboard answering questions or hand-holding agents.

### Target users

- **Home-lab operators** who want reproducible, self-hosted tooling
- Single-user / internal deployments (no multi-tenant SaaS)
- Users comfortable with Docker but who prefer not to write or maintain application code themselves

### Success criteria (v1)

| Criterion | Definition of done |
|-----------|-------------------|
| Usable dashboard | Mobile-friendly UI to create projects, monitor pipeline progress, view logs/diffs, and access live previews |
| Low-touch intake | User provides a short natural-language description; discovery/intake can proceed with defaults and auto-submit when the user is absent |
| Self-propelled agents | Architect → Developer → Tester pipeline runs autonomously, proposes improvements, and re-enters fix loops without manual intervention |
| Complete output | Finished project includes working frontend, API, tests, Dockerfile, `docker-compose.yml`, and `project.contract.yaml` |
| Easy deploy | `docker compose up -d` on the factory; generated apps run via their own `docker compose up -d --build` on port **8080** |
| Health visibility | Factory and every generated app expose **`GET /health`** for orchestration and smoke tests |

---

## Functional requirements

### FR-1 — Project lifecycle

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | User can create a project with a name and natural-language description | Must |
| FR-1.2 | System runs discovery/intake to refine scope with minimal user input | Must |
| FR-1.3 | Project progresses through explicit pipeline states (planning → implement → test → build → deploy → review → production) | Must |
| FR-1.4 | Failures transition to diagnose/fix loops with a hard cap (`max_attempts = 5`) before `AUTONOMOUSLY_BLOCKED` | Must |
| FR-1.5 | User can pause, inspect, and optionally respond to agent input requests when present | Should |
| FR-1.6 | Stale input requests auto-expire so agents continue without blocking indefinitely | Must |

### FR-2 — Autonomous agent pipeline

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | **Architect** agent produces `requirements.md`, `architecture.md`, and acceptance contract | Must |
| FR-2.2 | **Developer** agent implements features on an isolated git branch with commits | Must |
| FR-2.3 | **Tester** agent runs unit, integration, container smoke, and contract gates | Must |
| FR-2.4 | **Reviewer** agent (or equivalent gate) validates output against requirements before promotion | Should |
| FR-2.5 | Agents may propose and implement improvements beyond the initial spec without user approval for non-production changes | Must |
| FR-2.6 | Agent backend is pluggable (Cursor Cloud, Cursor local, local shell runner) | Must |

### FR-3 — Generated application contract

Every factory-produced application **must** conform to the following baseline:

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | **Python 3.12** runtime | Must |
| FR-3.2 | **FastAPI** HTTP API | Must |
| FR-3.3 | Browser-accessible web UI (static files served by FastAPI or equivalent) | Must |
| FR-3.4 | **`GET /health`** returning JSON `{"status": "ok", ...}` | Must |
| FR-3.5 | Docker image listening on **port 8080** | Must |
| FR-3.6 | `docker-compose.yml` with HTTP healthcheck against `/health` | Must |
| FR-3.7 | **pytest** test suite with unit and integration coverage | Must |
| FR-3.8 | `project.contract.yaml` documenting requirements, healthcheck, and test gates | Must |

### FR-4 — Dashboard & monitoring

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | Project list with current state, branch, preview URL, and image tag | Must |
| FR-4.2 | Live event stream (WebSocket) for agent commands, test results, and state transitions | Must |
| FR-4.3 | Task queue with role, status, attempt count, and history | Must |
| FR-4.4 | Progress digest, notes, and notifications for async check-ins | Must |
| FR-4.5 | Access to build artifacts, agent logs, and deployment history | Must |
| FR-4.6 | Mobile-responsive layout (readable on phone/tablet) | Must |
| FR-4.7 | One-click pipeline start and optional promote-to-production | Must |

### FR-5 — Deployment & previews

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | Factory deploys as a **single container** via `docker compose up -d` | Must |
| FR-5.2 | Live preview URLs allocated per project (ports 9010–9039) | Must |
| FR-5.3 | Pipeline builds project Docker images using the host Docker socket (build runner pattern) | Must |
| FR-5.4 | Staging smoke test hits `/health` before promotion | Must |
| FR-5.5 | Optional GitHub integration for repo push and remote CI | Should |

### FR-6 — Configuration & secrets

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | First-boot auto-configuration (encryption key, database, Redis) | Must |
| FR-6.2 | Optional Cursor API key and agent model selection via dashboard | Should |
| FR-6.3 | Per-project encrypted secrets storage | Should |
| FR-6.4 | Persistent data under configurable `FACTORY_DATA` mount | Must |

### FR-7 — Data persistence

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | **PostgreSQL** stores projects, tasks, events, deployments, settings, and discovery sessions | Must |
| FR-7.2 | **Redis** backs task queue and WebSocket fan-out | Must |
| FR-7.3 | Workspaces (git repos, logs, artifacts) persist on disk under `FACTORY_DATA` | Must |
| FR-7.4 | Full event history retained for audit and replay | Should |

---

## Non-functional requirements

### NFR-1 — Operability

| ID | Requirement |
|----|-------------|
| NFR-1.1 | Factory **`GET /health`** returns `200` with version metadata |
| NFR-1.2 | Container healthcheck script validates API readiness |
| NFR-1.3 | Default dashboard/API reachable at `http://localhost:8044` (configurable `HTTP_PORT`) |
| NFR-1.4 | No `.env` file required for first run |

### NFR-2 — Autonomy & resilience

| ID | Requirement |
|----|-------------|
| NFR-2.1 | Pipeline worker runs in-process or as a dedicated worker with Redis queue |
| NFR-2.2 | Agent concurrency limits prevent resource exhaustion |
| NFR-2.3 | Structured failure feedback includes logs, exit codes, and requirement IDs for fix prompts |
| NFR-2.4 | Input requests expire automatically; discovery intake can auto-submit |

### NFR-3 — Security (single-user baseline)

| ID | Requirement |
|----|-------------|
| NFR-3.1 | No authentication required by default (trusted internal network) |
| NFR-3.2 | Optional factory API key for reverse-proxy deployments |
| NFR-3.3 | Secrets encrypted at rest with instance-derived key |
| NFR-3.4 | Agent sandboxes must not receive raw production credentials or unrestricted host Docker access |

### NFR-4 — Quality & testing

| ID | Requirement |
|----|-------------|
| NFR-4.1 | Orchestrator covered by **pytest** (unit + integration) |
| NFR-4.2 | Generated apps must pass pytest with meaningful coverage of API routes and `/health` |
| NFR-4.3 | CI gate: container smoke test (`docker compose up`, healthcheck passes) before staging |
| NFR-4.4 | Contract tests validate OpenAPI shapes and acceptance criteria in `project.contract.yaml` |

### NFR-5 — UX

| ID | Requirement |
|----|-------------|
| NFR-5.1 | Minimal forms — prefer defaults, auto-detection, and agent-driven discovery |
| NFR-5.2 | Status visible at a glance for users checking in every 5–30+ minutes |
| NFR-5.3 | Notifications surface blockers (missing env vars, agent questions) without requiring constant polling |

### NFR-6 — Maintainability

| ID | Requirement |
|----|-------------|
| NFR-6.1 | Open-source MIT license |
| NFR-6.2 | Clear separation: control plane (orchestrator), dashboard, agent runners, workspace provisioner |
| NFR-6.3 | Git as source of truth — every code change committed on task branches |

---

## Exclusions (out of scope)

| Item | Rationale |
|------|-----------|
| Commercial / paid features | Open-source home-lab tool only |
| Multi-user auth / RBAC / OIDC | v1 is single-user; no login required |
| Non-Docker deployment targets | Kubernetes, bare-metal, serverless not in v1 |
| Real-time pair-programming UX | User is not expected to co-edit with agents |
| Billing, usage metering, or marketplace | Not applicable |
| Guaranteed SLAs or hosted SaaS | Self-hosted only |
| Mobile native apps | Mobile-friendly **web** UI only |
| Non-web generated apps (CLI-only, pure workers) | v1 targets full-stack web GUI Docker apps |

---

## Acceptance criteria (factory v1)

1. **`docker compose up -d`** starts the factory; dashboard loads at port 8044.
2. **`GET /health`** on the factory returns `{"status": "ok", "version": "..."}`.
3. User creates a project with a short description and clicks **Start pipeline** without further mandatory input.
4. Agents produce architect artifacts, implement a FastAPI app, pass pytest, build Docker, and deploy a preview.
5. Generated app responds on **port 8080** with **`GET /health`** returning `200`.
6. User can return after an extended absence and see progress, logs, preview URL, and completion status in the dashboard.
7. Generated app can be deployed independently: `cd project/repo && docker compose up -d --build`.

---

## Glossary

| Term | Definition |
|------|------------|
| **Factory** | The turtSlopFactory control plane + dashboard + embedded Postgres/Redis |
| **Project** | One user-initiated software product being built by agents |
| **Pipeline** | Ordered state machine from discovery through production |
| **Workspace** | Isolated git checkout + artifacts for a project or task |
| **Contract** | `project.contract.yaml` — machine-readable acceptance spec for testers |
| **Preview** | Live URL serving the built project image during development |
