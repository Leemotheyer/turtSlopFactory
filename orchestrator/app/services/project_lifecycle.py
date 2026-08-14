"""Delete a project and local workspace data (never touches GitHub)."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import DeploymentRow, EventRow, ProjectRow
from app.pipeline.executor import pipeline_executor
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


async def delete_project(
    session: AsyncSession,
    project_id: UUID,
    workspace: WorkspaceManager | None = None,
) -> None:
    row = await session.get(ProjectRow, project_id)
    if not row:
        raise ValueError("Project not found")

    if pipeline_executor.is_running(project_id):
        raise RuntimeError("Cannot delete project while pipeline is running")

    ws = workspace or WorkspaceManager()

    await session.execute(delete(DeploymentRow).where(DeploymentRow.project_id == project_id))
    await session.execute(delete(EventRow).where(EventRow.project_id == project_id))
    await session.delete(row)
    await session.commit()

    try:
        ws.delete_project(project_id)
    except Exception:
        logger.exception("Failed to delete workspace files for project %s", project_id)
        raise
