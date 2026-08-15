"""Resume the build pipeline after human feedback at review."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectRow
from app.models import ProjectState
from app.pipeline.executor import pipeline_executor
from app.services.pipeline_control import is_pipeline_paused
from app.services.pipeline_launcher import schedule_pipeline

logger = logging.getLogger(__name__)


def wants_merge_to_main(response: str, question: str = "") -> bool:
    normalized = response.strip().lower()
    if normalized in {"merge to main now", "merge to main", "yes, merge to main"}:
        return True
    if "merge" in question.lower() and "merge" in normalized and "main" in normalized:
        return True
    return False


def should_schedule_feedback_on_input_response(
    response: str,
    question: str,
    *,
    role: str = "",
) -> bool:
    """Return True only when a human answer should re-run implementation."""
    if role == "reviewer":
        return False

    question_lower = question.lower()
    response_lower = response.strip().lower()

    if wants_merge_to_main(response, question):
        return False
    if "merge" in question_lower and "branch" in question_lower:
        return False
    if "rate limit" in question_lower:
        return False
    if "database storage" in question_lower or "in-memory" in question_lower:
        return False

    skip_markers = ("skip", "defer", "not in v1", "keep on factory", "later")
    if any(marker in response_lower for marker in skip_markers):
        return False

    # Enrichment scope check — only restart when the human explicitly approves work.
    if "implement it" in question_lower or "out of scope" in question_lower:
        return response_lower.startswith("yes") and "implement" in response_lower

    return False


async def maybe_schedule_feedback_pipeline(session: AsyncSession, project_id: UUID) -> bool:
    """Start a feedback iteration when the project is waiting in REVIEW."""
    row = await session.get(ProjectRow, project_id)
    if not row or row.state != ProjectState.REVIEW.value:
        return False
    if pipeline_executor.is_running(project_id):
        return False
    if is_pipeline_paused(project_id):
        logger.info("Skipping feedback pipeline for %s — pipeline is paused", project_id)
        return False
    started = schedule_pipeline(project_id)
    if started:
        logger.info("Scheduled feedback pipeline for project %s", project_id)
    return started
