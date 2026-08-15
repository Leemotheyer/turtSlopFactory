import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.agents.factory import FactoryAgentRunner
from app.agents.prompt_builder import build_role_prompt
from app.models import AgentRole
from app.services.cursor_client import CursorClient
from app.workspace.manager import WorkspaceManager


def test_build_architect_prompt_includes_description():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {"name": "MyApp", "description": "Build a todo app"},
    )
    assert "MyApp" in prompt
    assert "todo app" in prompt
    assert "requirements.md" in prompt


def test_build_developer_prompt_forbids_manual_docker():
    prompt = build_role_prompt(
        AgentRole.DEVELOPER,
        {
            "name": "App",
            "description": "x",
            "preview_url": "http://localhost:8044/preview/abcd1234/",
            "preview_status": "running",
        },
    )
    assert "must NOT run" in prompt
    assert "http://localhost:8044/preview/abcd1234/" in prompt
    assert "docker compose" in prompt.lower() or "docker run" in prompt


def test_build_developer_stream_prompt():
    prompt = build_role_prompt(
        AgentRole.DEVELOPER,
        {"name": "App", "description": "x", "work_stream": "backend"},
    )
    assert "backend API" in prompt


@pytest.mark.asyncio
async def test_factory_runner_falls_back_without_api_key(tmp_path):
    workspace = WorkspaceManager(root=str(tmp_path))
    runner = FactoryAgentRunner(workspace)

    with patch("app.agents.factory.get_api_key", new_callable=AsyncMock, return_value=None):
        with patch("app.agents.factory.get_agent_backend", new_callable=AsyncMock, return_value="cursor_cloud"):
            run = await runner.run(
                AgentRole.ARCHITECT,
                uuid4(),
                uuid4(),
                str(workspace.repo_dir(uuid4())),
                {"name": "Test", "description": "A test app"},
            )

    assert run.success
    assert "requirements.md" in run.output or "Created" in run.output


@pytest.mark.asyncio
async def test_factory_runner_local_backend_uses_scaffold(tmp_path):
    workspace = WorkspaceManager(root=str(tmp_path))
    runner = FactoryAgentRunner(workspace)
    project_id = uuid4()

    with patch("app.agents.factory.get_agent_backend", new_callable=AsyncMock, return_value="local"):
        run = await runner.run(
            AgentRole.ARCHITECT,
            project_id,
            uuid4(),
            str(workspace.repo_dir(project_id)),
            {"name": "Test", "description": "A test app"},
        )

    assert run.success
    assert workspace.read_artifact(project_id, "requirements.md") is not None


@pytest.mark.asyncio
async def test_cursor_client_wait_for_run_completes():
    client = CursorClient("test-key")
    client.get_run = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {"status": "RUNNING"},
            {"status": "FINISHED", "result": {"text": "done"}},
        ]
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        run = await client.wait_for_run("agent-1", "run-1", poll_seconds=0.01, timeout_seconds=5)

    assert run["status"] == "FINISHED"
    await client.close()


@pytest.mark.asyncio
async def test_factory_settings_valid_backends():
    from app.services.factory_settings import VALID_AGENT_BACKENDS

    assert "cursor_cloud" in VALID_AGENT_BACKENDS
    assert "cursor_local" in VALID_AGENT_BACKENDS
    assert "local" in VALID_AGENT_BACKENDS
