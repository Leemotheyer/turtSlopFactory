import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.worker import DISCOVERY_QUEUE_KEY, PIPELINE_QUEUE_KEY, JobQueue


@pytest.mark.asyncio
async def test_process_loop_blpop_uses_key_list():
    """Redis blpop must receive a list of keys — a single string breaks the worker."""
    queue = JobQueue()
    project_id = uuid4()
    redis = AsyncMock()
    redis.blpop = AsyncMock(
        side_effect=[
            (DISCOVERY_QUEUE_KEY, str(project_id)),
            asyncio.CancelledError(),
        ]
    )
    queue._redis = redis

    with patch("app.worker.run_discovery", new_callable=AsyncMock) as run_discovery:
        task = asyncio.create_task(queue.process_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    redis.blpop.assert_called_with([PIPELINE_QUEUE_KEY, DISCOVERY_QUEUE_KEY], timeout=5)
    run_discovery.assert_awaited_once()
