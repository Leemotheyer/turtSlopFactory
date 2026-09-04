"""Lightweight ordered schema migrations.

``init_db`` runs ``Base.metadata.create_all`` (which creates *new tables* on any
database) and then applies these migrations in order. Migrations therefore only
need to handle changes that ``create_all`` cannot: value rewrites and columns
added to tables that already exist on older installs.

Every migration must be idempotent — fresh databases already have the final
schema from ``create_all``, so ALTERs are guarded by an existence check and
UPDATEs simply match zero rows.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)


async def _has_column(conn: AsyncConnection, table: str, column: str) -> bool:
    def _check(sync_conn) -> bool:
        inspector = inspect(sync_conn)
        if table not in inspector.get_table_names():
            return False
        return any(col["name"] == column for col in inspector.get_columns(table))

    return await conn.run_sync(_check)


async def add_column_if_missing(conn: AsyncConnection, table: str, column: str, ddl: str) -> None:
    """``ddl`` is the column definition, e.g. ``VARCHAR(64)`` or ``TEXT``."""
    if await _has_column(conn, table, column):
        return
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


# --- migration 0001: pipeline gate realignment -------------------------------
#
# Gates were renamed so that each project state matches the stage that runs
# there (previously the UNIT_TESTING state ran integration tests, the
# INTEGRATION_TESTING state ran the docker build, and so on). Persisted states
# shift one gate forward; UNIT_TESTING no longer exists as a project state
# (unit testing is a substage of IMPLEMENTING).

_STATE_SHIFT = {
    "UNIT_TESTING": "INTEGRATION_TESTING",
    "INTEGRATION_TESTING": "DOCKER_BUILD",
    "DOCKER_BUILD": "STAGING_DEPLOY",
    "STAGING_DEPLOY": "SMOKE_TESTING",
}


async def _migrate_0001_gate_realignment(conn: AsyncConnection) -> None:
    # Order matters: walk from the latest gate backwards so values are not
    # shifted twice by consecutive UPDATEs.
    for old in ("STAGING_DEPLOY", "DOCKER_BUILD", "INTEGRATION_TESTING", "UNIT_TESTING"):
        new = _STATE_SHIFT[old]
        await conn.execute(
            text("UPDATE projects SET state = :new WHERE state = :old"),
            {"new": new, "old": old},
        )

    # Workspace metadata mirrors failed_gate on disk; shift those too.
    try:
        from app.workspace.manager import WorkspaceManager

        workspace = WorkspaceManager()
        root = workspace.root / "projects"
        if root.is_dir():
            for meta_path in root.glob("*/metadata.json"):
                try:
                    import json

                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                failed = meta.get("failed_gate")
                if failed in _STATE_SHIFT:
                    meta["failed_gate"] = _STATE_SHIFT[failed]
                    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("Could not shift failed_gate values in workspace metadata", exc_info=True)


# --- migration 0002: prompt versions on tasks --------------------------------


async def _migrate_0002_task_prompt_version(conn: AsyncConnection) -> None:
    await add_column_if_missing(conn, "tasks", "prompt_version", "VARCHAR(64)")


# --- migration 0003: deployment verification / rollback ----------------------


async def _migrate_0003_deployment_verification(conn: AsyncConnection) -> None:
    await add_column_if_missing(conn, "deployments", "previous_tag", "VARCHAR(512)")
    await add_column_if_missing(conn, "deployments", "verification_status", "VARCHAR(32)")


# --- migration 0004: risk tier on input requests ------------------------------


async def _migrate_0004_input_request_risk(conn: AsyncConnection) -> None:
    await add_column_if_missing(conn, "input_requests", "risk", "VARCHAR(16) DEFAULT 'normal'")


MIGRATIONS: list[tuple[str, Callable[[AsyncConnection], Awaitable[None]]]] = [
    ("0001_gate_realignment", _migrate_0001_gate_realignment),
    ("0002_task_prompt_version", _migrate_0002_task_prompt_version),
    ("0003_deployment_verification", _migrate_0003_deployment_verification),
    ("0004_input_request_risk", _migrate_0004_input_request_risk),
]


async def run_migrations(engine: AsyncEngine) -> list[str]:
    """Apply pending migrations; returns the ids that ran."""
    applied: list[str] = []
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "id VARCHAR(128) PRIMARY KEY, applied_at TIMESTAMP NOT NULL)"
            )
        )
        result = await conn.execute(text("SELECT id FROM schema_migrations"))
        done = {row[0] for row in result}

        for migration_id, migrate in MIGRATIONS:
            if migration_id in done:
                continue
            logger.info("Applying migration %s", migration_id)
            await migrate(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (id, applied_at) VALUES (:id, :at)"),
                {"id": migration_id, "at": datetime.utcnow()},
            )
            applied.append(migration_id)
    return applied
