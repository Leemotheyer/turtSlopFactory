from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.factory import FactoryAgentRunner
from app.agents.prompt_builder import build_role_prompt
from app.models import AgentRole
from app.services.cursor_client import CursorClient
from app.workspace.manager import WorkspaceManager


class _FakeSession:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *args):
        return False


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
async def test_architect_without_repo_uses_cursor_cloud(tmp_path):
    workspace = WorkspaceManager(root=str(tmp_path))
    runner = FactoryAgentRunner(workspace)
    project_id = uuid4()
    runner._cloud.run_role = AsyncMock(return_value=(True, "planned comic reader", "bc-1"))  # type: ignore[method-assign]
    runner._cursor_local.run_role = AsyncMock(return_value=(False, "should not run", ""))  # type: ignore[method-assign]

    with patch("app.agents.factory.get_api_key", new_callable=AsyncMock, return_value="key"):
        with patch("app.agents.factory.get_agent_backend", new_callable=AsyncMock, return_value="cursor_cloud"):
            with patch(
                "app.agents.factory.get_agent_models",
                new_callable=AsyncMock,
                return_value={
                    "architect": "composer-2.5",
                    "developer": "composer-2.5",
                    "reviewer": "composer-2.5",
                },
            ):
                with patch("app.agents.factory.SessionLocal", _FakeSession):
                    with patch(
                        "app.services.agent_concurrency.wait_for_cursor_capacity",
                        new_callable=AsyncMock,
                    ) as wait:
                        wait.return_value = MagicMock(max_parallel=4, strategy="ok")
                        run = await runner.run(
                            AgentRole.ARCHITECT,
                            project_id,
                            uuid4(),
                            str(workspace.repo_dir(project_id)),
                            {"name": "Comic Reader", "description": "Read comics"},
                        )

    assert run.success
    runner._cloud.run_role.assert_awaited_once()
    runner._cursor_local.run_role.assert_not_awaited()
    log = (workspace.logs_dir(project_id) / "pipeline.log").read_text()
    assert "using Cursor Cloud without a GitHub repo" in log
    assert "falling back to local scaffold" not in log


@pytest.mark.asyncio
async def test_cursor_failure_does_not_scaffold_generic_app(tmp_path):
    workspace = WorkspaceManager(root=str(tmp_path))
    runner = FactoryAgentRunner(workspace)
    project_id = uuid4()
    runner._cursor_local.run_role = AsyncMock(  # type: ignore[method-assign]
        return_value=(False, "cursor-sdk is not installed in this factory image", "local-1")
    )

    with patch("app.agents.factory.get_api_key", new_callable=AsyncMock, return_value="key"):
        with patch("app.agents.factory.get_agent_backend", new_callable=AsyncMock, return_value="cursor_cloud"):
            with patch(
                "app.agents.factory.get_agent_models",
                new_callable=AsyncMock,
                return_value={
                    "architect": "composer-2.5",
                    "developer": "composer-2.5",
                    "reviewer": "composer-2.5",
                },
            ):
                with patch("app.agents.factory.SessionLocal", _FakeSession):
                    run = await runner.run(
                        AgentRole.DEVELOPER,
                        project_id,
                        uuid4(),
                        str(workspace.repo_dir(project_id)),
                        {"name": "Comic Reader", "description": "Read comics"},
                    )

    assert run.success is False
    assert "cursor-sdk" in run.output
    assert not (workspace.repo_dir(project_id) / "app" / "main.py").exists()
    log = (workspace.logs_dir(project_id) / "pipeline.log").read_text()
    assert "Cursor unsuccessful: cursor-sdk" in log
    assert "falling back to local scaffold" not in log


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


def test_run_text_calls_method():
    from app.agents.cursor_local_runner import _run_text

    class Run:
        def text(self):
            return "hello from agent"

    assert _run_text(Run()) == "hello from agent"


def test_run_text_string_attribute():
    from app.agents.cursor_local_runner import _run_text

    class Run:
        text = "plain"

    assert _run_text(Run()) == "plain"


@pytest.mark.asyncio
async def test_factory_settings_valid_backends():
    from app.services.factory_settings import VALID_AGENT_BACKENDS

    assert "cursor_cloud" in VALID_AGENT_BACKENDS
    assert "cursor_local" in VALID_AGENT_BACKENDS
    assert "local" in VALID_AGENT_BACKENDS
