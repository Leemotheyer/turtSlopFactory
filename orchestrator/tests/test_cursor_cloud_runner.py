import pytest
from uuid import uuid4

from app.agents.cursor_cloud_runner import CursorCloudRunner, _as_dict
from app.workspace.manager import WorkspaceManager


@pytest.fixture
def workspace(tmp_path):
    return WorkspaceManager(str(tmp_path))


def test_as_dict_coerces_non_dict():
    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict("text") == {}
    assert _as_dict(None) == {}


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
