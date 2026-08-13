import json
import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.config import settings
from app.pipeline.executor import pipeline_executor

logger = logging.getLogger(__name__)

QUEUE_KEY = "factory:pipeline:queue"


class PipelineQueue:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def enqueue(self, project_id: UUID) -> None:
        if not self._redis:
            await self.connect()
        assert self._redis
        await self._redis.rpush(QUEUE_KEY, str(project_id))
        logger.info("Enqueued pipeline for project %s", project_id)

    async def process_loop(self) -> None:
        if not self._redis:
            await self.connect()
        assert self._redis

        logger.info("Pipeline worker started")
        while True:
            result = await self._redis.blpop(QUEUE_KEY, timeout=5)
            if not result:
                continue
            _, project_id_str = result
            try:
                project_id = UUID(project_id_str)
                logger.info("Processing pipeline for %s", project_id)
                await pipeline_executor.run_pipeline(project_id)
            except Exception:
                logger.exception("Failed to process project %s", project_id_str)


pipeline_queue = PipelineQueue()
