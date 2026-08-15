"""Resume the build pipeline after human feedback at review."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectRow
from app.models import ProjectState
from app.pipeline.executor import pipeline_executor
from app.services.pipeline_launcher import schedule_pipeline

logger = logging.getLogger(__name__)


def wants_merge_to_main(response: str, question: str = "") -> bool:
    normalized = response.strip().lower()
    if normalized in {"merge to main now", "merge to main", "yes, merge to main"}:
        return True
    if "merge" in question.lower() and "merge" in normalized and "main" in normalized:
        return True
    return False


async def maybe_schedule_feedback_pipeline(session: AsyncSession, project_id: UUID) -> bool:
    """Start a feedback iteration when the project is waiting in REVIEW."""
    row = await session.get(ProjectRow, project_id)
    if not row or row.state != ProjectState.REVIEW.value:
        return False
    if pipeline_executor.is_running(project_id):
        return False
    started = schedule_pipeline(project_id)
    if started:
        logger.info("Scheduled feedback pipeline for project %s", project_id)
    return started
