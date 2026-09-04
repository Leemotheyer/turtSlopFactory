import pytest
from uuid import uuid4

from unittest.mock import AsyncMock, patch

from app.agents.cursor_cloud_runner import (
    CursorCloudRunner,
    _as_dict,
    _parse_created_agent,
    _run_result_text,
)
from app.models import AgentRole
from app.services.cursor_client import CursorApiError
from app.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(str(tmp_path))


def test_as_dict_coerces_non_dict():
    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict("text") == {}
    assert _as_dict(None) == {}


def test_parse_created_agent_nested_and_flat():
    agent_id, run_id, agent = _parse_created_agent(
        {
            "agent": {"id": "bc-1", "url": "https://cursor.com/agents/bc-1", "latestRunId": "run-9"},
            "run": {"id": "run-1"},
        }
    )
    assert agent_id == "bc-1"
    assert run_id == "run-1"
    assert agent["url"].endswith("bc-1")

    agent_id, run_id, _ = _parse_created_agent({"id": "bc-2", "latestRunId": "run-2"})
    assert agent_id == "bc-2"
    assert run_id == "run-2"


def test_run_result_text_string_or_object():
    assert _run_result_text({"result": "# Requirements\nhello"}) == "# Requirements\nhello"
    assert _run_result_text({"result": {"text": "nested"}}) == "nested"
    assert _run_result_text({"text": "top"}) == "top"
    assert _run_result_text({"result": {}}) == ""


@pytest.mark.asyncio
async def test_sync_repo_handles_string_result_and_branch_list(workspace, tmp_path):
    runner = CursorCloudRunner(workspace)
    final_run = {
        "result": "done",
        "git": {"branches": ["factory/turtslopfactory-feba34e7"]},
    }

    message = await runner._sync_repo_from_cloud(
        __import__("uuid").uuid4(),
        str(tmp_path),
        "https://github.com/example/repo.git",
        final_run,
    )

    assert "Could not clone" in message or "Synced" in message or "Cloned" in message


@pytest.mark.asyncio
async def test_sync_repo_does_not_crash_on_string_branch_entries(workspace, tmp_path):
    runner = CursorCloudRunner(workspace)
    final_run = {
        "result": {"text": "ok", "git": {"branches": ["main"]}},
    }

    message = await runner._sync_repo_from_cloud(
        __import__("uuid").uuid4(),
        str(tmp_path),
        "https://github.com/example/repo.git",
        final_run,
    )

    assert isinstance(message, str)


def _cloud_client(create_return=None, create_side_effect=None, final_run=None):
    client = AsyncMock()
    if create_side_effect is not None:
        client.create_agent = AsyncMock(side_effect=create_side_effect)
    else:
        client.create_agent = AsyncMock(
            return_value=create_return
            or {
                "agent": {"id": "bc-arch", "url": "https://cursor.com/agents/bc-arch"},
                "run": {"id": "run-arch"},
            }
        )
    client.wait_for_run = AsyncMock(
        return_value=final_run
        or {
            "status": "FINISHED",
            "result": "# Requirements\nNeed a reader\n\n# Architecture\nFastAPI on 8080\n",
        }
    )
    client.get_agent = AsyncMock(return_value={})
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_no_repo_architect_writes_docs_from_string_result(workspace):
    runner = CursorCloudRunner(workspace)
    project_id = uuid4()
    client = _cloud_client()

    with patch("app.agents.cursor_cloud_runner.CursorClient", return_value=client):
        with patch(
            "app.services.agent_concurrency.reclaim_idle_factory_agents",
            new_callable=AsyncMock,
            return_value=4,
        ):
            success, output, agent_id = await runner.run_role(
                "key",
                AgentRole.ARCHITECT,
                project_id,
                uuid4(),
                str(workspace.repo_dir(project_id)),
                {"name": "Comic Reader", "description": "Read comics"},
                model_id="composer-2.5",
            )

    assert success is True
    assert agent_id == "bc-arch"
    assert "Requirements" in output
    assert workspace.read_artifact(project_id, "requirements.md")
    assert workspace.read_artifact(project_id, "architecture.md")
    client.create_agent.assert_awaited()
    assert client.create_agent.await_args.kwargs["mode"] == "agent"
    assert client.create_agent.await_args.kwargs["repos"] is None


@pytest.mark.asyncio
async def test_architect_salvages_error_run_with_reply_text(workspace):
    runner = CursorCloudRunner(workspace)
    project_id = uuid4()
    client = _cloud_client(
        final_run={
            "status": "ERROR",
            "result": "# Requirements\nStill useful\n\n# Architecture\nKeep going\n",
        }
    )

    with patch("app.agents.cursor_cloud_runner.CursorClient", return_value=client):
        with patch(
            "app.services.agent_concurrency.reclaim_idle_factory_agents",
            new_callable=AsyncMock,
            return_value=0,
        ):
            success, output, _ = await runner.run_role(
                "key",
                AgentRole.ARCHITECT,
                project_id,
                uuid4(),
                str(workspace.repo_dir(project_id)),
                {"name": "App", "description": "x"},
            )

    assert success is True
    assert "Still useful" in output
    assert "requirements.md" in workspace.list_artifacts(project_id)


@pytest.mark.asyncio
async def test_create_retries_without_model_on_invalid_model(workspace):
    runner = CursorCloudRunner(workspace)
    project_id = uuid4()
    client = _cloud_client()
    client.create_agent = AsyncMock(
        side_effect=[
            CursorApiError(400, "Unknown model composer-2.5-fast"),
            {
                "agent": {"id": "bc-arch", "url": "https://cursor.com/agents/bc-arch"},
                "run": {"id": "run-arch"},
            },
        ]
    )

    with patch("app.agents.cursor_cloud_runner.CursorClient", return_value=client):
        with patch(
            "app.services.agent_concurrency.reclaim_idle_factory_agents",
            new_callable=AsyncMock,
            return_value=0,
        ):
            success, _, _ = await runner.run_role(
                "key",
                AgentRole.ARCHITECT,
                project_id,
                uuid4(),
                str(workspace.repo_dir(project_id)),
                {"name": "App", "description": "x"},
                model_id="composer-2.5-fast",
            )

    assert success is True
    assert client.create_agent.await_count == 2
    assert client.create_agent.await_args_list[1].kwargs["model_id"] is None
