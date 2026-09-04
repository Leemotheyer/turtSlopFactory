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
| http://localhost:8044 | Dashboard + API (single port) |
| http://localhost:8044/preview/{project-id}/ | Live project previews (via gateway) |

Everything else — encryption key, hostname, Cursor, API key — is auto-configured or set in the dashboard.

## What runs

**One container** (`factory`) includes everything:

| Component | Role |
|-----------|------|
| **Caddy** | Gateway — dashboard + `/api` + `/ws` on port 80 |
| **FastAPI** | API + pipeline worker (Docker socket for builds) |
| **Next.js** | Dashboard UI |
| **PostgreSQL** | Projects, settings, secrets metadata |
| **Redis** | Task queue + WebSocket fan-out |

Only two mounts are required:

- `FACTORY_DATA` → `/data` (all persistent state)
- `/var/run/docker.sock` (pipeline builds)

## Portainer

Paste [`portainer-stack.yml`](portainer-stack.yml) into **Stacks → Web editor**, or use [`portainer-stack.build.yml`](portainer-stack.build.yml) to build on your server (no GHCR pull).

If deploy fails with **`denied`**, the GHCR image is private — see [docs/PORTAINER.md](docs/PORTAINER.md).

Open `http://<server-ip>:8044`.

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
| Encryption key | Generated on first boot, saved under `FACTORY_DATA` |
| API + dashboard URL | Single origin on port 8044 |
| Preview hostname | Auto-detected from your browser / `X-Forwarded-Host` |
| Database / Redis | Embedded in the container, data under `FACTORY_DATA` |
| CORS | Open for self-hosted |

## Persistent data

Set **`FACTORY_DATA`** to control where all state lives (default `./data`). Only the Docker socket is mounted separately.

```
${FACTORY_DATA}/
  config/       encryption key, optional local.env
  workspaces/   project repos, artifacts, logs
  postgres/     database files
  redis/        queue / pubsub persistence
```

Copy `data/config/local.env.example` to `${FACTORY_DATA}/config/local.env` for optional env overrides.

```bash
FACTORY_DATA=/mnt/factory docker compose up -d
```

**Quotes:** not needed for normal paths (`./data`, `/mnt/factory`). Only use quotes if the path contains spaces, e.g. `FACTORY_DATA="/opt/my factory"`. In Portainer’s environment UI, enter the path **without** quotes.

Legacy installs that used `FACTORY_DATA_DIR` still work — compose falls back to it when `FACTORY_DATA` is unset.

## Optional env overrides

```env
FACTORY_DATA=./data     # host path for all persistent data (default)
HTTP_PORT=8044          # default; change if 8044 is taken
IMAGE_TAG=latest        # pin GHCR release (use `dev` on the dev branch)
PUBLIC_HOST=factory.example.com
```

## How the factory decides "done"

Every project gets a **contract** — requirements with testable acceptance criteria —
generated during planning and editable in the dashboard. Pipeline stages record
**evidence** (test results mapped to requirements via `test_<req_id>_*` naming, health
probes, builds), an **adversarial stage** tries to break the staging deploy, and a
deterministic **acceptance evaluator** blocks review until every requirement is verified
(or explicitly waived). Failures are diagnosed (infra vs app), remembered across runs,
and fixed bugs must ship a regression test. Deploys are observed after cutover and roll
back automatically on health regression.

## Benchmarks

The factory's own quality is measured, not guessed:

```bash
python scripts/run_benchmarks.py        # full pipeline on fixture specs (no docker/LLM needed)
```

CI runs these on every push — a failing benchmark means the factory itself regressed.

## Hardened deploy (optional)

Scope Docker access through a socket proxy instead of mounting the raw socket:

```bash
docker compose -f docker-compose.yml -f docker-compose.hardened.yml up -d
```

Preview containers are always capped (memory/CPU/pids) regardless of mode.

## Local development

Run API + dashboard on the host with postgres/redis from compose:

```bash
cd orchestrator && pip install -e ".[dev,cursor]"
docker compose -f docker-compose.deps.yml up -d
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
