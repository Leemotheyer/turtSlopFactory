import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.local_runner import LocalAgentRunner
from app.models import AgentRole
from app.workspace.manager import WorkspaceManager
from app.workspace.scaffolder import scaffold_base


@pytest.mark.asyncio
async def test_parallel_backend_and_frontend_streams():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = WorkspaceManager(tmp)
        runner = LocalAgentRunner(workspace)
        project_id = uuid4()
        repo = workspace.repo_dir(project_id)
        scaffold_base(repo, "Parallel App", "Test parallel build")

        backend_task = uuid4()
        frontend_task = uuid4()
        base_context = {"name": "Parallel App", "description": "Test parallel build"}

        backend_run, frontend_run = await asyncio.gather(
            runner.run(
                AgentRole.DEVELOPER,
                project_id,
                backend_task,
                str(repo),
                {**base_context, "work_stream": "backend"},
            ),
            runner.run(
                AgentRole.DEVELOPER,
                project_id,
                frontend_task,
                str(repo),
                {**base_context, "work_stream": "frontend"},
            ),
        )

        assert backend_run.success
        assert frontend_run.success
        assert (repo / "app" / "main.py").read_text().count("/api/items") >= 1
        assert (repo / "app" / "static" / "index.html").exists()


@pytest.mark.asyncio
async def test_parallel_feature_stream():
    with tempfile.TemporaryDirectory() as tmp:
        workspace = WorkspaceManager(tmp)
        runner = LocalAgentRunner(workspace)
        project_id = uuid4()
        repo = workspace.repo_dir(project_id)
        scaffold_base(repo, "Feature App", "Features")

        run = await runner.run(
            AgentRole.DEVELOPER,
            project_id,
            uuid4(),
            str(repo),
            {
                "name": "Feature App",
                "description": "Features",
                "work_stream": "feature",
                "feature_id": "export-csv",
                "feature_content": "Export to CSV",
            },
        )
        assert run.success
        assert (repo / "app" / "features" / "export-csv.py").exists()
