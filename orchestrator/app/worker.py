import logging
from uuid import UUID

import redis.asyncio as aioredis

from app.config import settings
from app.database import SessionLocal
from app.pipeline.executor import pipeline_executor
from app.services.discovery import run_discovery

logger = logging.getLogger(__name__)

PIPELINE_QUEUE_KEY = "factory:pipeline:queue"
DISCOVERY_QUEUE_KEY = "factory:discovery:queue"


class JobQueue:
    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def enqueue_pipeline(self, project_id: UUID) -> None:
        if not self._redis:
            await self.connect()
        assert self._redis
        await self._redis.rpush(PIPELINE_QUEUE_KEY, str(project_id))
        logger.info("Enqueued pipeline for project %s", project_id)

    async def enqueue_discovery(self, project_id: UUID) -> None:
        if not self._redis:
            await self.connect()
        assert self._redis
        await self._redis.rpush(DISCOVERY_QUEUE_KEY, str(project_id))
        logger.info("Enqueued discovery for project %s", project_id)

    async def process_loop(self) -> None:
        if not self._redis:
            await self.connect()
        assert self._redis

        logger.info("Job worker started (pipeline + discovery)")
        while True:
            result = await self._redis.blpop(
                [PIPELINE_QUEUE_KEY, DISCOVERY_QUEUE_KEY], timeout=5
            )
            if not result:
                continue
            queue_name, project_id_str = result
            try:
                project_id = UUID(project_id_str)
                if queue_name == DISCOVERY_QUEUE_KEY:
                    logger.info("Running discovery for %s", project_id)
                    async with SessionLocal() as session:
                        await run_discovery(session, project_id)
                else:
                    logger.info("Processing pipeline for %s", project_id)
                    await pipeline_executor.run_pipeline(project_id)
            except Exception:
                logger.exception("Failed job %s for project %s", queue_name, project_id_str)


pipeline_queue = JobQueue()
