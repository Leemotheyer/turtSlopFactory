import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.pipeline_launcher import schedule_pipeline


@pytest.mark.asyncio
async def test_schedule_pipeline_skips_when_already_running():
    project_id = uuid4()
    with patch("app.services.pipeline_launcher.pipeline_executor") as executor:
        executor.is_running.return_value = True
        assert schedule_pipeline(project_id) is False
        executor.run_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_pipeline_starts_background_task():
    project_id = uuid4()
    with patch("app.services.pipeline_launcher.pipeline_executor") as executor:
        executor.is_running.return_value = False
        executor.run_pipeline = AsyncMock()
        assert schedule_pipeline(project_id) is True
        await asyncio.sleep(0.05)
        executor.run_pipeline.assert_awaited_once_with(project_id)
