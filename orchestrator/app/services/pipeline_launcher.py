"""Start the build pipeline without relying solely on the Redis worker queue."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.pipeline.executor import pipeline_executor

logger = logging.getLogger(__name__)


def schedule_pipeline(project_id: UUID) -> bool:
    """Run the pipeline in the background. Returns False if already running."""
    if pipeline_executor.is_running(project_id):
        return False
    asyncio.create_task(pipeline_executor.run_pipeline(project_id))
    logger.info("Scheduled pipeline for project %s", project_id)
    return True
