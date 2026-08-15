from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.pipeline.executor import PipelineExecutor, PipelineStopped
from app.services.pipeline_launcher import stop_pipeline


@pytest.mark.asyncio
async def test_request_stop_when_not_running():
    executor = PipelineExecutor()
    project_id = uuid4()
    assert executor.request_stop(project_id) is False


@pytest.mark.asyncio
async def test_request_stop_marks_and_cancels_task():
    executor = PipelineExecutor()
    project_id = uuid4()
    executor._running.add(project_id)

    task = MagicMock()
    task.done.return_value = False
    executor._pipeline_tasks[project_id] = task

    assert executor.request_stop(project_id) is True
    assert executor.is_stop_requested(project_id)
    task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_check_stop_raises():
    executor = PipelineExecutor()
    project_id = uuid4()
    executor._stop_requested.add(project_id)
    with pytest.raises(PipelineStopped):
        executor._check_stop(project_id)


def test_stop_pipeline_delegates_to_executor():
    project_id = uuid4()
    with patch("app.services.pipeline_launcher.pipeline_executor") as executor:
        executor.request_stop.return_value = True
        assert stop_pipeline(project_id) is True
        executor.request_stop.assert_called_once_with(project_id)
