#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${FACTORY_DATA:-/data}"
export PGDATA="${DATA_ROOT}/postgres"
PG_MAJOR="$(ls /usr/lib/postgresql | sort -V | tail -1)"
PG_BIN="/usr/lib/postgresql/${PG_MAJOR}/bin"

mkdir -p "${DATA_ROOT}/config" "${DATA_ROOT}/workspaces" "${DATA_ROOT}/postgres" "${DATA_ROOT}/redis"

# Upgrade legacy layout: /data/factory -> /data/config
if [ -d "${DATA_ROOT}/factory" ] && [ ! -e "${DATA_ROOT}/config/encryption.key" ] && [ ! -e "${DATA_ROOT}/config/local.env" ]; then
  echo "Migrating ${DATA_ROOT}/factory -> ${DATA_ROOT}/config"
  cp -a "${DATA_ROOT}/factory/." "${DATA_ROOT}/config/" 2>/dev/null || true
fi

if [ ! -f "${PGDATA}/PG_VERSION" ]; then
  echo "Initializing PostgreSQL ${PG_MAJOR} in ${PGDATA}..."
  chown -R postgres:postgres "${PGDATA}"
  su postgres -s /bin/bash -c "${PG_BIN}/initdb -D '${PGDATA}'"
  {
    echo "listen_addresses = '127.0.0.1'"
    echo "port = 5432"
  } >> "${PGDATA}/postgresql.conf"
  echo "host all all 127.0.0.1/32 scram-sha-256" >> "${PGDATA}/pg_hba.conf"
  su postgres -s /bin/bash -c "${PG_BIN}/pg_ctl -D '${PGDATA}' -w start"
  su postgres -s /bin/bash -c "psql -v ON_ERROR_STOP=1 -c \"CREATE USER factory WITH PASSWORD 'factory' CREATEDB;\""
  su postgres -s /bin/bash -c "createdb -O factory factory"
  su postgres -s /bin/bash -c "${PG_BIN}/pg_ctl -D '${PGDATA}' -w stop"
  echo "PostgreSQL ready."
fi

chown -R postgres:postgres "${PGDATA}"

if [ -S /var/run/docker.sock ]; then
  docker network create factory-preview 2>/dev/null || true
  docker network connect factory-preview "${HOSTNAME}" 2>/dev/null || true
fi

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
