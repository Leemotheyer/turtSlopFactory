# Deploying in Portainer

## Fastest path (recommended)

1. **Stacks** → **Add stack**
2. Paste the contents of [`portainer-stack.yml`](../portainer-stack.yml) into the **Web editor**
3. **Deploy** — no environment variables, no bind mounts
4. Open `http://<your-server-ip>`

The stack includes:

- **gateway** — Caddy on port 80 (dashboard + API at one URL)
- **factory** — API + worker combined, with Docker socket for pipeline builds
- **dashboard**, **postgres**, **redis**

Live previews: `http://<server-ip>:8081` … `:8099`

## Git repository method

| Field | Value |
|-------|-------|
| Repository URL | `https://github.com/Leemotheyer/turtSlopFactory` |
| Compose path | `docker-compose.yml` |

Requires the repo checkout on the Portainer host (for `deploy/Caddyfile`). Use the web-editor stack above if you prefer paste-only deploy.

## Requirements

- **Docker Standalone** endpoint (worker needs `/var/run/docker.sock`)
- Port **80** available (or set `HTTP_PORT` in compose)
- Ports **8081–8099** for live previews

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
