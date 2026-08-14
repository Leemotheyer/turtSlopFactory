# turtSlopFactory — all-in-one image (API, worker, dashboard, gateway, postgres, redis)
# syntax=docker/dockerfile:1

FROM node:22-alpine AS dashboard-build
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install
COPY dashboard/ .
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_URL=
ARG NEXT_PUBLIC_WS_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
RUN npm run build

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    docker.io \
    postgresql \
    postgresql-client \
    redis-server \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

ARG CADDY_VERSION=2.9.1
RUN curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/bin caddy

RUN pip install --no-cache-dir hatchling

COPY orchestrator/pyproject.toml .
COPY orchestrator/app ./app
COPY orchestrator/worker_main.py .
RUN pip install --no-cache-dir .

COPY --from=dashboard-build /app/public /dashboard/public
COPY --from=dashboard-build /app/.next/standalone /dashboard/
COPY --from=dashboard-build /app/.next/static /dashboard/.next/static

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/entrypoint.sh /entrypoint.sh
COPY deploy/wait-for-services.sh /deploy/wait-for-services.sh
COPY deploy/supervisord.conf /etc/supervisor/conf.d/factory.conf

RUN chmod +x /entrypoint.sh /deploy/wait-for-services.sh

ENV FACTORY_DATA=/data \
    FACTORY_CONFIG_DIR=/data/config \
    WORKSPACE_ROOT=/data/workspaces \
    DATABASE_URL=postgresql+asyncpg://factory:factory@127.0.0.1:5432/factory \
    REDIS_URL=redis://127.0.0.1:6379/0 \
    WORKER_ENABLED=true \
    CORS_ALLOW_ALL=true \
    TRUST_PROXY_HEADERS=true

EXPOSE 80
EXPOSE 9010-9039

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=45s \
    CMD curl -fsS http://127.0.0.1/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
