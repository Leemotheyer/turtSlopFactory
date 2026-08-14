import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.local_runner import LocalAgentRunner
from app.models import AgentRole
from app.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(str(tmp_path))


@pytest.fixture
def runner(workspace):
    return LocalAgentRunner(workspace)


@pytest.mark.asyncio
async def test_architect_creates_artifacts(runner, workspace):
    project_id = uuid4()
    task_id = uuid4()
    run = await runner.run(
        AgentRole.ARCHITECT,
        project_id,
        task_id,
        "",
        {"name": "My App", "description": "Test app"},
    )
    assert run.success
    assert "requirements.md" in workspace.list_artifacts(project_id)


@pytest.mark.asyncio
async def test_developer_scaffolds_code(runner, workspace):
    project_id = uuid4()
    task_id = uuid4()
    run = await runner.run(
        AgentRole.DEVELOPER,
        project_id,
        task_id,
        "",
        {"name": "My App", "description": "Test app"},
    )
    assert run.success
    assert (workspace.repo_dir(project_id) / "app" / "main.py").exists()


@pytest.mark.asyncio
async def test_unit_tests_pass(runner, workspace):
    project_id = uuid4()
    # Scaffold first
    await runner.run(
        AgentRole.DEVELOPER,
        project_id,
        uuid4(),
        "",
        {"name": "Test App", "description": "Unit test app"},
    )
    success, output = await runner._tester(project_id, {"test_stage": "unit"})
    assert success, output


@pytest.mark.asyncio
async def test_smoke_uses_factory_preview_upstream(runner, workspace):
    from unittest.mock import AsyncMock, MagicMock, patch

    project_id = uuid4()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "ok"}
    response.text = '{"status":"ok"}'

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = False

    with patch("app.agents.local_runner.httpx.AsyncClient", return_value=mock_client):
        success, output = await runner._tester(
            project_id,
            {
                "test_stage": "smoke",
                "preview_upstream": "http://factory-live-abcd1234:8080",
                "preview_health_path": "/health",
            },
        )

    assert success, output
    mock_client.get.assert_awaited()
    assert mock_client.get.await_args.args[0] == "http://factory-live-abcd1234:8080/health"
