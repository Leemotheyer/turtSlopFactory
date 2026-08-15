from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.pipeline.executor import PipelineExecutor, PipelineStopped
from app.services.pipeline_control import is_pipeline_paused, set_pipeline_paused


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


@pytest.mark.asyncio
async def test_stop_pipeline_pauses_and_finalizes():
    project_id = uuid4()
    with patch("app.services.pipeline_launcher.pipeline_executor") as executor:
        executor.force_stop = AsyncMock()
        from app.services.pipeline_launcher import stop_pipeline

        result = await stop_pipeline(project_id)
        assert result is True
        executor.force_stop.assert_awaited_once_with(project_id)


def test_schedule_pipeline_respects_pause(tmp_path, monkeypatch):
    project_id = uuid4()
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(ws_root))
    monkeypatch.setattr("app.config.settings.workspace_root", str(ws_root))

    set_pipeline_paused(project_id, True)
    assert is_pipeline_paused(project_id)

    with patch("app.services.pipeline_launcher.pipeline_executor") as executor:
        executor.is_running.return_value = False
        from app.services.pipeline_launcher import schedule_pipeline

        assert schedule_pipeline(project_id) is False
        executor.run_pipeline.assert_not_called()


def test_schedule_pipeline_force_clears_pause(tmp_path, monkeypatch):
    project_id = uuid4()
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(ws_root))
    monkeypatch.setattr("app.config.settings.workspace_root", str(ws_root))

    set_pipeline_paused(project_id, True)

    with patch("app.services.pipeline_launcher.pipeline_executor") as executor, patch(
        "app.services.pipeline_launcher.asyncio.create_task"
    ) as create_task:
        executor.is_running.return_value = False
        create_task.return_value = MagicMock()
        from app.services.pipeline_launcher import schedule_pipeline

        assert schedule_pipeline(project_id, force=True) is True
        assert not is_pipeline_paused(project_id)
