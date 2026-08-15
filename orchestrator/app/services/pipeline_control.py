"""Pipeline pause/stop helpers and stale-state reconciliation."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import EventRow, TaskRow
from app.models import EventType, TaskStatus
from app.services.cursor_connection import get_api_key
from app.services.cursor_client import CursorApiError, CursorClient
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)
workspace = WorkspaceManager()


def is_pipeline_paused(project_id: UUID) -> bool:
    return bool(workspace.load_metadata(project_id).get("pipeline_paused"))


def set_pipeline_paused(project_id: UUID, paused: bool) -> None:
    meta = workspace.load_metadata(project_id)
    if paused:
        meta["pipeline_paused"] = True
        meta["pipeline_paused_at"] = datetime.utcnow().isoformat()
    else:
        meta.pop("pipeline_paused", None)
        meta.pop("pipeline_paused_at", None)
    workspace.save_metadata(project_id, meta)


def clear_live_agents(project_id: UUID) -> None:
    meta = workspace.load_metadata(project_id)
    meta.pop("live_agents", None)
    meta.pop("pipeline_substage", None)
    meta.pop("enrichment", None)
    workspace.save_metadata(project_id, meta)


def collect_cloud_agent_ids(project_id: UUID, session: AsyncSession | None = None) -> set[str]:
    """Gather Cursor cloud agent ids tied to this project."""
    ids: set[str] = set()
    meta = workspace.load_metadata(project_id)
    for live in (meta.get("live_agents") or {}).values():
        agent_id = live.get("agent_id")
        if isinstance(agent_id, str) and agent_id.startswith("bc-"):
            ids.add(agent_id)

    if session is None:
        return ids

    task_result = session.execute(
        select(TaskRow.id).where(
            TaskRow.project_id == project_id,
            TaskRow.status == TaskStatus.RUNNING.value,
        )
    )
    running_task_ids = {row[0] for row in task_result.all()}
    if not running_task_ids:
        return ids

    event_result = session.execute(
        select(EventRow.agent_id, EventRow.task_id, EventRow.payload)
        .where(
            EventRow.project_id == project_id,
            EventRow.task_id.in_(running_task_ids),
        )
        .order_by(EventRow.created_at.desc())
        .limit(200)
    )
    for agent_id, _task_id, payload in event_result.all():
        if isinstance(agent_id, str) and agent_id.startswith("bc-"):
            ids.add(agent_id)
        if isinstance(payload, dict):
            cursor_url = payload.get("cursor_url") or ""
            if "/agents/bc-" in cursor_url:
                part = cursor_url.rstrip("/").split("/")[-1]
                if part.startswith("bc-"):
                    ids.add(part)
    return ids


async def archive_project_cloud_agents(session: AsyncSession, project_id: UUID) -> int:
    """Archive Cursor cloud agents so they stop consuming slots and billing."""
    agent_ids = collect_cloud_agent_ids(project_id, session)
    if not agent_ids:
        return 0

    api_key = await get_api_key(session)
    if not api_key:
        logger.warning("Cannot archive cloud agents for %s — no Cursor API key", project_id)
        return 0

    archived = 0
    async with CursorClient(api_key) as client:
        for agent_id in sorted(agent_ids):
            try:
                await client.archive_agent(agent_id)
                archived += 1
                workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[stop] Archived Cursor cloud agent {agent_id}",
                )
            except CursorApiError as exc:
                logger.warning("Could not archive agent %s: %s", agent_id, exc.message)
            except Exception:
                logger.exception("Failed archiving agent %s for project %s", agent_id, project_id)
    return archived


async def fail_running_tasks(session: AsyncSession, project_id: UUID, *, reason: str) -> int:
    result = await session.execute(
        select(TaskRow).where(
            TaskRow.project_id == project_id,
            TaskRow.status == TaskStatus.RUNNING.value,
        )
    )
    count = 0
    for task in result.scalars():
        task.status = TaskStatus.FAILED.value
        task.updated_at = datetime.utcnow()
        count += 1
    if count:
        await session.commit()
        workspace.append_log(project_id, "pipeline.log", f"[stop] Marked {count} running task(s) failed: {reason}")
    return count


async def reconcile_stale_running_tasks(session: AsyncSession) -> int:
    """On factory startup, clear tasks left RUNNING after a container restart."""
    result = await session.execute(
        select(TaskRow).where(TaskRow.status == TaskStatus.RUNNING.value)
    )
    count = 0
    for task in result.scalars():
        task.status = TaskStatus.FAILED.value
        task.updated_at = datetime.utcnow()
        count += 1
    if count:
        await session.commit()
        logger.info("Reconciled %d stale RUNNING task(s) after factory restart", count)

    root = workspace.root / "projects"
    if root.is_dir():
        for project_dir in root.iterdir():
            if not project_dir.is_dir():
                continue
            try:
                project_id = UUID(project_dir.name)
            except ValueError:
                continue
            meta = workspace.load_metadata(project_id)
            if meta.get("live_agents") or meta.get("pipeline_substage") or meta.get("enrichment"):
                meta.pop("live_agents", None)
                meta.pop("pipeline_substage", None)
                meta.pop("enrichment", None)
                workspace.save_metadata(project_id, meta)
    return count
