import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import EventRow
from app.models import EventType, FactoryEvent


class EventBus:
    CHANNEL = "factory:events"

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._subscribers: set[asyncio.Queue[FactoryEvent]] = set()

    async def connect(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def publish(self, session: AsyncSession, event: FactoryEvent) -> FactoryEvent:
        row = EventRow(
            id=event.id,
            type=event.type.value,
            project_id=event.project_id,
            task_id=event.task_id,
            agent_id=event.agent_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        session.add(row)
        await session.commit()

        if self._redis:
            await self._redis.publish(self.CHANNEL, event.model_dump_json())

        for queue in list(self._subscribers):
            await queue.put(event)

        return event

    def subscribe(self) -> asyncio.Queue[FactoryEvent]:
        queue: asyncio.Queue[FactoryEvent] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[FactoryEvent]) -> None:
        self._subscribers.discard(queue)

    async def listen_redis(self) -> AsyncIterator[FactoryEvent]:
        if not self._redis:
            return

        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                data = json.loads(message["data"])
                yield FactoryEvent.model_validate(data)
        finally:
            await pubsub.unsubscribe(self.CHANNEL)
            await pubsub.aclose()


event_bus = EventBus()
