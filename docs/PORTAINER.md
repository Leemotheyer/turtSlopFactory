# Deploying in Portainer

## Fastest path (pull prebuilt image)

1. **Stacks** → **Add stack**
2. Paste the contents of [`portainer-stack.yml`](../portainer-stack.yml) into the **Web editor**
3. **Deploy** — one service, one named volume
4. Open `http://<your-server-ip>:8044`

The stack runs a **single container** with the dashboard, API, worker, gateway, PostgreSQL, and Redis.

Live previews are served through the factory gateway at `/preview/{project-id}/` — no extra host ports required.

### `Error response from daemon: denied`

This almost always means **Docker could not pull the image from GHCR** (the package is private by default).

**Fix A — make the package public (one-time, repo owner):**

1. GitHub → your profile → **Packages** → `turtslopfactory`
2. **Package settings** → **Change visibility** → **Public**

New CI builds also attempt to set visibility to public automatically.

**Fix B — add registry credentials in Portainer:**

1. **Registries** → **Add registry**
2. Provider: **Custom**
3. Name: `ghcr.io`
4. URL: `ghcr.io`
5. Username: your GitHub username
6. Password: a GitHub PAT with `read:packages` scope
7. Redeploy the stack

**Fix C — build from source (no GHCR):**

Use [`portainer-stack.build.yml`](../portainer-stack.build.yml) or deploy from Git:

| Field | Value |
|-------|-------|
| Repository URL | `https://github.com/Leemotheyer/turtSlopFactory` |
| Compose path | `portainer-stack.build.yml` |

First deploy takes longer while the image builds on your server.

## Git repository method (compose pull)

| Field | Value |
|-------|-------|
| Repository URL | `https://github.com/Leemotheyer/turtSlopFactory` |
| Compose path | `docker-compose.yml` |

### `FACTORY_DATA` — host path for all persistent files

Set this in the stack **Environment variables** (or a `.env` file next to compose) when using `docker-compose.yml` with a bind mount.

| Where | Example | Quotes? |
|-------|---------|---------|
| Shell | `FACTORY_DATA=./data docker compose up -d` | No quotes needed for normal paths |
| Shell (spaces in path) | `FACTORY_DATA="/opt/my factory" docker compose up -d` | Quotes required |
| `.env` file | `FACTORY_DATA=./data` | No quotes unless the path contains spaces |
| Portainer env UI | `/opt/turtslopfactory` | **No quotes** — enter the path only |

Inside the container, data always lives under `/data` (`config`, `workspaces`, `postgres`, `redis`).

Example bind mount in compose:

```yaml
services:
  factory:
    volumes:
      - /opt/turtslopfactory:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

With Portainer env var `FACTORY_DATA=/opt/turtslopfactory`, `docker-compose.yml` already expands `${FACTORY_DATA}:/data`.

## Persistence

| Path in container | Contents |
|-------------------|----------|
| `/data/config` | Encryption key, optional `local.env` |
| `/data/workspaces` | Project repos and artifacts |
| `/data/postgres` | Database |
| `/data/redis` | Queue / pubsub |

The default web-editor stack uses one named volume `factory_data` mounted at `/data` (no `FACTORY_DATA` needed).

## Requirements

- **Docker Standalone** endpoint (needs `/var/run/docker.sock` for pipeline builds)
- Port **8044** available (or change the host port mapping)
- Live previews use the gateway path `/preview/…` (no extra host ports)

## After deploy

No setup wizard required on LAN — hostname is auto-detected on first visit.

Optional configuration in the dashboard **Cursor** menu:

- Connect Cursor API key
- Set factory API key
- Change preview hostname

## Install script (SSH)

```bash
curl -fsSL https://raw.githubusercontent.com/Leemotheyer/turtSlopFactory/main/install.sh | bash
```
