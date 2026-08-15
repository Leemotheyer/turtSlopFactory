"""Start/stop the build pipeline with pause support."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.pipeline.executor import pipeline_executor
from app.services.pipeline_control import is_pipeline_paused, set_pipeline_paused

logger = logging.getLogger(__name__)


def schedule_pipeline(project_id: UUID, *, force: bool = False) -> bool:
    """Run the pipeline in the background. Returns False if already running or paused."""
    if is_pipeline_paused(project_id) and not force:
        logger.info("Pipeline paused for project %s — not auto-starting", project_id)
        return False
    if pipeline_executor.is_running(project_id):
        return False
    if force:
        set_pipeline_paused(project_id, False)
    task = asyncio.create_task(pipeline_executor.run_pipeline(project_id))
    pipeline_executor.register_task(project_id, task)
    logger.info("Scheduled pipeline for project %s", project_id)
    return True


async def stop_pipeline(project_id: UUID) -> bool:
    """Hard stop: pause auto-start, cancel pipeline, archive agents, fail running tasks."""
    await pipeline_executor.force_stop(project_id)
    logger.info("Stop completed for pipeline project %s", project_id)
    return True
