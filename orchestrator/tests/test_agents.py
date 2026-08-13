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
