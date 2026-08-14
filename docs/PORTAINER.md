# Deploying in Portainer

## Fastest path (recommended)

1. **Stacks** → **Add stack**
2. Paste the contents of [`portainer-stack.yml`](../portainer-stack.yml) into the **Web editor**
3. **Deploy** — one service, one named volume, no env vars required
4. Open `http://<your-server-ip>:8044`

The stack runs a **single container** with the dashboard, API, worker, gateway, PostgreSQL, and Redis.

Live previews: `http://<server-ip>:9010` … `:9039`

## Git repository method

| Field | Value |
|-------|-------|
| Repository URL | `https://github.com/Leemotheyer/turtSlopFactory` |
| Compose path | `docker-compose.yml` |

Set `FACTORY_DATA` in the stack environment if you want a host bind mount instead of the default `./data`:

```yaml
services:
  factory:
    volumes:
      - /opt/turtslopfactory:/data
      - /var/run/docker.sock:/var/run/docker.sock
```

## Persistence

| Path in container | Contents |
|-------------------|----------|
| `/data/config` | Encryption key, optional `local.env` |
| `/data/workspaces` | Project repos and artifacts |
| `/data/postgres` | Database |
| `/data/redis` | Queue / pubsub |

Portainer’s web-editor stack uses one named volume `factory_data` mounted at `/data`.

## Requirements

- **Docker Standalone** endpoint (needs `/var/run/docker.sock` for pipeline builds)
- Port **8044** available (or set `HTTP_PORT` in compose)
- Ports **9010–9039** for live previews

## GHCR authentication

If image pulls fail, add registry `ghcr.io` with a GitHub PAT (`read:packages`).

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
