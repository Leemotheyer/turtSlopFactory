# turtSlopFactory — all-in-one image (API, worker, dashboard, gateway, postgres, redis)
# syntax=docker/dockerfile:1

# Build dashboard on Debian/glibc — must match the runtime image (not Alpine/musl).
FROM node:22-bookworm-slim AS dashboard-build
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

FROM node:22-bookworm-slim AS node-runtime

FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    docker.io \
    git \
    postgresql \
    postgresql-client \
    redis-server \
    redis-tools \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

ARG CADDY_VERSION=2.9.1
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) CADDY_ARCH=amd64 ;; \
      arm64) CADDY_ARCH=arm64 ;; \
      arm) CADDY_ARCH=armv7 ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${CADDY_ARCH}.tar.gz" \
      | tar -xz -C /usr/bin caddy; \
    caddy version

RUN pip install --no-cache-dir hatchling

COPY orchestrator/pyproject.toml .
COPY orchestrator/app ./app
COPY orchestrator/worker_main.py .
RUN pip install --no-cache-dir ".[cursor]"

COPY --from=dashboard-build /app/public /dashboard/public
COPY --from=dashboard-build /app/.next/standalone /dashboard/
COPY --from=dashboard-build /app/.next/static /dashboard/.next/static
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node

RUN node --version \
    && test -x /usr/bin/git \
    && test -x /usr/bin/redis-cli \
    && test -x /usr/bin/pg_isready

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/entrypoint.sh /entrypoint.sh
COPY deploy/wait-for-services.sh /deploy/wait-for-services.sh
COPY deploy/start-postgres.sh /deploy/start-postgres.sh
COPY deploy/healthcheck.sh /deploy/healthcheck.sh
COPY deploy/supervisord.conf /etc/supervisor/conf.d/factory.conf

RUN sed -i 's/\r$//' /entrypoint.sh /deploy/*.sh

RUN chmod +x /entrypoint.sh /deploy/wait-for-services.sh /deploy/start-postgres.sh /deploy/healthcheck.sh

ENV FACTORY_DATA=/data \
    FACTORY_CONFIG_DIR=/data/config \
    WORKSPACE_ROOT=/data/workspaces \
    DATABASE_URL=postgresql+asyncpg://factory:factory@127.0.0.1:5432/factory \
    REDIS_URL=redis://127.0.0.1:6379/0 \
    WORKER_ENABLED=true \
    CORS_ALLOW_ALL=true \
    TRUST_PROXY_HEADERS=true

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --retries=8 --start-period=90s \
    CMD /deploy/healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
