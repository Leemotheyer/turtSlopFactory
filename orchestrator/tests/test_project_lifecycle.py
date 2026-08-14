import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.db_models import ProjectRow
from app.services.project_lifecycle import delete_project
from app.workspace.manager import WorkspaceManager


def test_workspace_delete_project_removes_files():
    with tempfile.TemporaryDirectory() as tmp:
        ws = WorkspaceManager(root=tmp)
        project_id = uuid4()
        ws.project_dir(project_id)
        marker = ws.project_dir(project_id) / "marker.txt"
        marker.write_text("local")

        ws.delete_project(project_id)

        project_path = Path(tmp) / "projects" / str(project_id)
        assert not project_path.exists()


@pytest.mark.asyncio
@patch("app.pipeline.executor.pipeline_executor.is_running", return_value=False)
async def test_delete_project_removes_workspace(_is_running):
    project_id = uuid4()
    with tempfile.TemporaryDirectory() as tmp:
        ws = WorkspaceManager(root=tmp)
        ws.project_dir(project_id)
        (ws.project_dir(project_id) / "marker.txt").write_text("local")
        project_path = Path(tmp) / "projects" / str(project_id)

        row = ProjectRow(id=project_id, name="Remove me", description="Temporary")
        session = AsyncMock()
        session.get = AsyncMock(return_value=row)
        session.execute = AsyncMock()
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        await delete_project(session, project_id, workspace=ws)

        session.delete.assert_called_once_with(row)
        assert not project_path.exists()
