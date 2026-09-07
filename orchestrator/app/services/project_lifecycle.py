"""Delete a project and local workspace data (never touches GitHub)."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import (
    ArchitectureDecisionRow,
    DeploymentRow,
    EvidenceRow,
    EventRow,
    FailureRecordRow,
    KnownIssueRow,
    PipelineRunRow,
    ProjectContractRow,
    ProjectRow,
    RequirementRow,
)
from app.pipeline.executor import pipeline_executor
from app.services.preview_manager import stop_preview
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_PREVIEW_STOP_TIMEOUT_SECONDS = 20.0


async def _delete_project_rows(session: AsyncSession, project_id: UUID) -> None:
    """Remove all database rows for a project (dependency order)."""
    await session.execute(delete(EvidenceRow).where(EvidenceRow.project_id == project_id))
    await session.execute(delete(RequirementRow).where(RequirementRow.project_id == project_id))
    await session.execute(delete(ProjectContractRow).where(ProjectContractRow.project_id == project_id))
    await session.execute(
        delete(ArchitectureDecisionRow).where(ArchitectureDecisionRow.project_id == project_id)
    )
    await session.execute(delete(FailureRecordRow).where(FailureRecordRow.project_id == project_id))
    await session.execute(delete(KnownIssueRow).where(KnownIssueRow.project_id == project_id))
    await session.execute(delete(PipelineRunRow).where(PipelineRunRow.project_id == project_id))
    await session.execute(delete(DeploymentRow).where(DeploymentRow.project_id == project_id))
    await session.execute(delete(EventRow).where(EventRow.project_id == project_id))

    row = await session.get(ProjectRow, project_id)
    if row is not None:
        await session.delete(row)


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

    meta = ws.load_metadata(project_id)
    try:
        await asyncio.wait_for(
            stop_preview(
                project_id,
                container_name=meta.get("preview_container"),
                ephemeral_image=meta.get("preview_ephemeral_image"),
            ),
            timeout=_PREVIEW_STOP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out stopping preview for project %s after %.0fs — continuing delete",
            project_id,
            _PREVIEW_STOP_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Failed to stop preview for project %s", project_id)

    await _delete_project_rows(session, project_id)
    await session.commit()

    try:
        ws.delete_project(project_id)
    except Exception:
        logger.exception("Failed to delete workspace files for project %s", project_id)
        raise
