from uuid import uuid4

import pytest

from app.db_models import ProjectRow
from app.pipeline.executor import PipelineExecutor, _STAGE_UNIT_TESTING
from app.models import ProjectState
from app.services.repo_analysis import analyze_repo


def test_load_failed_gate_does_not_skip_implementation_on_unit_test_failure():
    executor = PipelineExecutor()
    project_id = uuid4()
    context: dict = {}
    executor.workspace.save_metadata(
        project_id,
        {
            "failed_gate": ProjectState.IMPLEMENTING.value,
            "failed_substage": _STAGE_UNIT_TESTING,
        },
    )

    gate = executor._load_failed_gate(project_id, context)

    assert gate == ProjectState.IMPLEMENTING
    assert context.get("failed_substage") == _STAGE_UNIT_TESTING
    assert "implementation_complete" not in context


def test_persist_last_failure_roundtrip():
    executor = PipelineExecutor()
    project_id = uuid4()
    context = {"last_failure": "pytest FAILED: assert 404 == 200"}

    executor._persist_last_failure(project_id, context)
    meta = executor.workspace.load_metadata(project_id)

    assert "pytest FAILED" in meta["last_failure"]


@pytest.mark.asyncio
async def test_ensure_runnable_app_skips_existing_non_fastapi_repo(workspace):
    executor = PipelineExecutor()
    executor.workspace = workspace
    project_id = uuid4()
    project = ProjectRow(
        id=project_id,
        name="Existing App",
        description="Continue my Next app",
        repo_url="https://github.com/acme/existing-app",
    )
    repo = workspace.repo_dir(project_id)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "package.json").write_text('{"dependencies":{"next":"14"}}')
    for i in range(10):
        (repo / f"page{i}.tsx").write_text("export default function P() {}\n")

    context = {"repo_analysis": analyze_repo(repo)}
    await executor._ensure_runnable_app(project, context)

    assert not (repo / "app" / "main.py").exists()


@pytest.mark.asyncio
async def test_ensure_runnable_app_repairs_broken_main(workspace):
    executor = PipelineExecutor()
    executor.workspace = workspace
    project_id = uuid4()
    project = ProjectRow(id=project_id, name="Repair Me", description="Test")
    repo = workspace.repo_dir(project_id)
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "app").mkdir()
    (repo / "app" / "main.py").write_text("this is not valid python!!!")

    await executor._ensure_runnable_app(project)

    assert executor._app_source_valid(repo)
    assert (repo / "tests" / "test_app.py").exists()
