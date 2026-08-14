#!/usr/bin/env bash
set -euo pipefail

PGDATA="${FACTORY_DATA:-/data}/postgres"
PG_MAJOR="$(ls /usr/lib/postgresql | sort -V | tail -1)"
exec "/usr/lib/postgresql/${PG_MAJOR}/bin/postgres" -D "${PGDATA}"
