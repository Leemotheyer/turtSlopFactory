# turtSlopFactory — Requirements

## Overview

**turtSlopFactory** is a self-hosted, agentic software factory for home-lab operators. A user describes an idea in plain language, starts a project, and walks away. Autonomous development agents plan, implement, test, Docker-build, and iterate until the project produces a **full, releasable web GUI application** packaged as Docker images the user can deploy anywhere.

The factory itself is a **full-stack web application** (FastAPI API + browser dashboard). Generated output applications follow a standardized stack: **Python 3.12**, **FastAPI**, **Docker on port 8080**, **pytest with coverage**, and a **`/health` endpoint**.

### Problem statement

Building and maintaining small internal tools or side projects requires sustained attention: scaffolding, implementation, testing, containerization, and deployment. Home-lab users want working software without sitting through long Q&A sessions or micromanaging an AI assistant.

### Solution

turtSlopFactory orchestrates specialized agents (discovery, architect, developer, tester, reviewer) through a deterministic pipeline. The user provides a high-level goal, optionally answers a minimal intake form, and checks back periodically via a mobile-friendly dashboard to see progress, previews, and the finished product.

### Success criteria (v1)

v1 is complete when:

1. A user can **start a project in under a minute** with minimal input (name + description).
2. The pipeline runs **autonomously** — agents propose improvements, implement them, and iterate without continuous user presence.
3. The user returns after minutes, hours, or days to find a **complete, Docker-deployable web application** with API and browser UI.
4. The factory dashboard is **fully functional and mobile-friendly**, showing project status, live events, previews, and deployment artifacts.
5. Generated apps expose **`GET /health`**, run in Docker on **port 8080**, and pass **pytest** with meaningful coverage.

---

## Target users

| Persona | Needs |
|---------|-------|
| **Home-lab operator** | Self-hosted tooling, Docker-first deploys, no SaaS lock-in |
| **Hands-off supervisor** | Start-and-forget workflow; check in occasionally, not continuously |
| **Single operator** | No multi-tenant auth; one person, one factory instance |

---

## Functional requirements

### FR-1: Project lifecycle

| ID | Requirement |
|----|-------------|
| FR-1.1 | User can create a project with a name and natural-language description. |
| FR-1.2 | Project progresses through explicit pipeline states: discovery → planning → implementing → testing → Docker build → staging → review → production. |
| FR-1.3 | Failures transition to diagnose/fix loops (max 5 attempts per gate) before blocking for human review. |
| FR-1.4 | User can delete projects and view historical events, logs, and artifacts. |
| FR-1.5 | User can promote a finished project to production and merge work branches to `main`. |

### FR-2: Minimal user interaction

| ID | Requirement |
|----|-------------|
| FR-2.1 | Discovery agent generates a loose plan and optional intake form from the initial description. |
| FR-2.2 | Intake forms auto-submit with sensible defaults when the user does not respond within a configurable window. |
| FR-2.3 | Agents must not block on user input for routine decisions; prefer autonomous defaults. |
| FR-2.4 | When input is required (secrets, env vars, API keys), the factory surfaces **actionable notifications** the user can resolve asynchronously. |
| FR-2.5 | Dashboard shows progress digests and notes so the user can understand status at a glance without reading raw logs. |

### FR-3: Self-propelled development agents

| ID | Requirement |
|----|-------------|
| FR-3.1 | **Discovery** agent refines vague ideas into structured intake and a discovery plan. |
| FR-3.2 | **Architect** agent produces `requirements.md`, `architecture.md`, API schema, and acceptance criteria before code is written. |
| FR-3.3 | **Developer** agent implements features, writes tests, commits to isolated feature branches, and proposes improvements. |
| FR-3.4 | **Tester** agent runs unit, integration, and smoke tests; validates Docker healthchecks and contracts. |
| FR-3.5 | **Reviewer** agent evaluates diffs and test evidence against requirements before promotion. |
| FR-3.6 | Agents iterate autonomously: on failure, structured fix prompts are generated and re-queued without user intervention. |

### FR-4: Generated application standard

Every project the factory produces must meet these output requirements:

| ID | Requirement |
|----|-------------|
| FR-4.1 | **Stack:** Python 3.12 + FastAPI backend with a browser-accessible web UI (static or server-rendered). |
| FR-4.2 | **Docker:** `Dockerfile` and `docker-compose.yml` exposing the app on **port 8080**. |
| FR-4.3 | **Health:** `GET /health` returns HTTP 200 with JSON `{"status": "ok", ...}`. |
| FR-4.4 | **Tests:** pytest suite with unit and integration tests; coverage reported in CI gates. |
| FR-4.5 | **Deployability:** `docker compose up -d --build` produces a running, health-checked container. |
| FR-4.6 | **Contract:** `project.contract.yaml` documents requirements, healthcheck, and gate configuration. |

### FR-5: Dashboard and API

| ID | Requirement |
|----|-------------|
| FR-5.1 | Browser UI lists projects, pipeline progress, tasks, and notifications. |
| FR-5.2 | Live event stream (WebSocket) shows agent activity, state transitions, and test results. |
| FR-5.3 | User can start/resume the pipeline, view artifacts (`requirements.md`, logs, diffs), and open live previews. |
| FR-5.4 | REST API exposes projects, tasks, events, pipeline control, secrets, settings, and integrations. |
| FR-5.5 | Factory exposes **`GET /health`** for container orchestration healthchecks. |
| FR-5.6 | UI is **responsive and mobile-friendly** (readable on phone/tablet viewports). |

### FR-6: Integrations (optional but supported)

| ID | Requirement |
|----|-------------|
| FR-6.1 | Cursor Cloud / local agent backend for LLM-powered roles. |
| FR-6.2 | GitHub token for repo linking, branch isolation, and push verification. |
| FR-6.3 | Per-project encrypted secrets storage for runtime env vars. |
| FR-6.4 | Live preview URLs for in-progress web apps via gateway proxy. |

### FR-7: Data persistence

| ID | Requirement |
|----|-------------|
| FR-7.1 | PostgreSQL stores projects, tasks, events, discovery sessions, notifications, secrets metadata, and deployments. |
| FR-7.2 | Workspaces (git repos, artifacts, logs) persist on disk under configurable `FACTORY_DATA`. |
| FR-7.3 | Redis backs the task queue and WebSocket event fan-out. |

---

## Non-functional requirements

### NFR-1: Deployment and operations

| ID | Requirement |
|----|-------------|
| NFR-1.1 | Single-command deploy: `docker compose up -d` exposes dashboard + API on one port (default **8044**). |
| NFR-1.2 | All factory state lives under one mount (`FACTORY_DATA`); only Docker socket is additionally required for builds. |
| NFR-1.3 | Encryption key auto-generated on first boot; optional env overrides via `local.env`. |
| NFR-1.4 | Factory container includes embedded PostgreSQL and Redis (no external deps required for MVP). |

### NFR-2: Security (single-user scope)

| ID | Requirement |
|----|-------------|
| NFR-2.1 | No user authentication for MVP — intended for trusted home-lab networks. |
| NFR-2.2 | Optional factory API key for write protection when exposed beyond localhost. |
| NFR-2.3 | Project secrets encrypted at rest; agents receive secrets at runtime, not in prompts. |
| NFR-2.4 | Agent sandboxes do not mount the host Docker socket; builds go through a controlled runner. |

### NFR-3: Reliability and observability

| ID | Requirement |
|----|-------------|
| NFR-3.1 | All state transitions and agent commands persisted as events for replay and audit. |
| NFR-3.2 | Pipeline worker survives restarts; in-flight projects can be resumed. |
| NFR-3.3 | Healthchecks on factory container and generated app containers. |

### NFR-4: Performance and concurrency

| ID | Requirement |
|----|-------------|
| NFR-4.1 | Support parallel agent work units where safe (e.g., independent features). |
| NFR-4.2 | Respect Cursor API concurrency limits with queuing and backoff. |
| NFR-4.3 | Dashboard remains responsive while long-running agent tasks execute in background. |

### NFR-5: Testing (factory codebase)

| ID | Requirement |
|----|-------------|
| NFR-5.1 | Orchestrator tested with **pytest**; target meaningful coverage of state machine, pipeline gates, and API handlers. |
| NFR-5.2 | CI runs test suite on changes to the control plane. |

---

## Exclusions (out of scope)

| ID | Exclusion | Rationale |
|----|-----------|-----------|
| EX-1 | **Commercial / paid features** | Open-source, self-hosted project |
| EX-2 | **Multi-user auth / RBAC** | Single-user home-lab tool for v1 |
| EX-3 | **SaaS hosting** | User runs their own Docker instance |
| EX-4 | **Non-Docker deploy targets** | Kubernetes, serverless, bare-metal are future concerns |
| EX-5 | **Continuous user Q&A** | User is supervisor, not pair programmer |
| EX-6 | **Mobile native apps** | Mobile-friendly web UI only |
| EX-7 | **Generated apps without web UI** | MVP targets full web GUI Docker apps specifically |

---

## Acceptance criteria checklist

- [ ] `docker compose up -d` starts factory; dashboard reachable on port 8044
- [ ] `GET /health` on factory returns `{"status": "ok"}`
- [ ] User creates project with name + description; pipeline starts autonomously
- [ ] Discovery/intake completes without mandatory user presence (auto-submit works)
- [ ] Architect artifacts (`requirements.md`, `architecture.md`) generated per project
- [ ] Developer produces Python 3.12 + FastAPI app with web UI
- [ ] Generated app: Docker on 8080, `/health` passes, pytest suite green
- [ ] Dashboard shows live progress on mobile viewport
- [ ] User returns after extended idle period to completed/blocked project with clear next action
- [ ] `docker compose up` in generated project repo yields running container

---

## Glossary

| Term | Definition |
|------|------------|
| **Factory** | The turtSlopFactory control plane (this repository) |
| **Project** | A user-initiated software build tracked by the factory |
| **Gate** | A pipeline stage that must pass before advancing (e.g., unit testing) |
| **Workspace** | Isolated directory containing a project's git repo and artifacts |
| **Agent** | An autonomous worker role (architect, developer, etc.) |
| **Preview** | Live URL proxying to an in-progress app's dev or Docker server |
