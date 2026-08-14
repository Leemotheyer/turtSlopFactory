# Deploying turtSlopFactory in Portainer

No `.env` file is required. The factory auto-generates its encryption key and uses sensible defaults for the database.

## One-minute deploy

1. In Portainer go to **Stacks** → **Add stack**
2. Name: `turtslopfactory`
3. **Web editor** — paste the contents of [`docker-compose.prod.yml`](../docker-compose.prod.yml) from this repo  
   **or** use **Git repository**:
   - URL: `https://github.com/Leemotheyer/turtSlopFactory`
   - Compose path: `docker-compose.prod.yml`
4. Click **Deploy the stack** (no environment variables needed)
5. Open `http://<your-server-ip>:3000`
6. Complete the **Quick setup** banner:
   - Confirm **server hostname** (pre-filled with your browser hostname)
   - Optionally set a **factory API key**
7. In **Cursor** menu: connect your Cursor API key when ready

## Ports

| Port | Purpose |
|------|---------|
| 3000 | Dashboard |
| 8000 | API |
| 8081–8099 | Live project previews |

## Worker / Docker socket

The `worker` service mounts `/var/run/docker.sock` so pipelines can build images and run live previews. This requires a **Docker Standalone** endpoint in Portainer (not Swarm).

## GHCR pull errors

If image pulls fail, add a registry in Portainer:

- URL: `ghcr.io`
- Username: GitHub username
- Password: GitHub PAT with `read:packages`

Or build from source using `docker-compose.yml` instead.

## Optional overrides

Only set these if you need them:

| Variable | When to use |
|----------|-------------|
| `IMAGE_TAG` | Pin a release instead of `latest` |
| `PUBLIC_HOST` | Override preview hostname without using the dashboard |
| `API_KEY` | Lock API before first dashboard visit |

Everything else (Cursor key, agent backend, preview host) is configured in the dashboard after deploy.
