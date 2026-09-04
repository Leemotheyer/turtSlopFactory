"""End-to-end pipeline test: local backend, sqlite, no docker.

Drives ``run_pipeline`` through every gate and asserts the evidence-based
architecture holds together: contract saved, requirements synced, evidence
recorded, acceptance evaluated, review reached, run metrics finalized.
"""

import asyncio
from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.db_models import (
    DeploymentRow,
    EvidenceRow,
    FactorySettingsRow,
    PipelineRunRow,
    ProjectContractRow,
    ProjectRow,
    RequirementRow,
)
from app.models import ProjectState


@pytest_asyncio.fixture
async def pipeline_env(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        session.add(FactorySettingsRow(id=1, agent_backend="local", setup_complete=True))
        await session.commit()

    yield session_factory

    await engine.dispose()


@pytest.mark.asyncio
async def test_full_pipeline_reaches_review_with_verified_requirements(pipeline_env, tmp_path):
    from app.pipeline.executor import PipelineExecutor
    from app.workspace.manager import WorkspaceManager

    session_factory = pipeline_env
    project_id = uuid4()

    async with session_factory() as session:
        session.add(
            ProjectRow(
                id=project_id,
                name="E2E App",
                description="A small item tracker used to verify the factory pipeline",
                state=ProjectState.PLANNING.value,
                max_enrichment_passes=0,
            )
        )
        await session.commit()

    executor = PipelineExecutor()
    executor.workspace = WorkspaceManager(str(tmp_path))
    executor.runner.workspace = executor.workspace
    executor.runner._cloud.workspace = executor.workspace
    executor.runner._cursor_local.workspace = executor.workspace
    executor.test_runner.agent.workspace = executor.workspace

    with ExitStack() as stack:
        stack.enter_context(patch("app.pipeline.executor.SessionLocal", session_factory))
        stack.enter_context(patch("app.agents.factory.SessionLocal", session_factory))
        # No docker in CI — force simulated build/deploy paths.
        stack.enter_context(patch.object(executor.runner, "docker_available", lambda: False))

        await asyncio.wait_for(executor.run_pipeline(project_id), timeout=600)

    async with session_factory() as session:
        project = await session.get(ProjectRow, project_id)
        assert project.state == ProjectState.REVIEW.value, (
            f"expected REVIEW, got {project.state}"
        )

        # Contract persisted with requirements.
        contracts = (
            (await session.execute(
                select(ProjectContractRow).where(ProjectContractRow.project_id == project_id)
            )).scalars().all()
        )
        assert contracts, "planning must persist a project contract"

        # Requirements synced and every one verified (or waived).
        requirements = (
            (await session.execute(
                select(RequirementRow).where(RequirementRow.project_id == project_id)
            )).scalars().all()
        )
        assert requirements, "contract requirements must be synced to rows"
        statuses = {req.req_id: req.status for req in requirements}
        assert all(s in ("verified", "waived") for s in statuses.values()), statuses

        # Evidence recorded, including requirement-mapped test evidence.
        evidence = (
            (await session.execute(
                select(EvidenceRow).where(EvidenceRow.project_id == project_id)
            )).scalars().all()
        )
        kinds = {row.kind for row in evidence}
        assert "test_run" in kinds
        assert "build" in kinds
        assert any(row.requirement_id is not None for row in evidence), (
            "at least one evidence row must link to a requirement"
        )

        # Deployments recorded (staging simulated).
        deployments = (
            (await session.execute(
                select(DeploymentRow).where(DeploymentRow.project_id == project_id)
            )).scalars().all()
        )
        assert any(dep.environment == "staging" for dep in deployments)

        # Run metrics finalized.
        runs = (
            (await session.execute(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
            )).scalars().all()
        )
        assert len(runs) == 1
        assert runs[0].outcome == "completed"
        assert runs[0].finished_at is not None
        assert runs[0].prompt_versions.get("developer", "").startswith("developer-v")

    # Artifacts: contract, acceptance report, adversary report, work plan.
    artifacts = executor.workspace.list_artifacts(project_id)
    assert "contract.json" in artifacts
    assert "acceptance-report.json" in artifacts
    assert "adversary-report.json" in artifacts
    assert "work-plan.json" in artifacts
    assert "build-manifest.json" in artifacts

    # The repo mirrors the contract for agents and humans.
    repo = executor.workspace.repo_dir(project_id)
    assert (repo / "project.contract.yaml").is_file()
    assert (repo / "tests" / "acceptance").is_dir()


@pytest.mark.asyncio
async def test_failure_ladder_diagnoses_fixes_and_pins_regression(pipeline_env, tmp_path):
    """Plant one unit-test failure: diagnosis → fix → regression test → REVIEW."""
    from app.db_models import FailureRecordRow
    from app.pipeline.executor import PipelineExecutor
    from app.workspace.manager import WorkspaceManager

    session_factory = pipeline_env
    project_id = uuid4()

    async with session_factory() as session:
        session.add(
            ProjectRow(
                id=project_id,
                name="Flaky App",
                description="An app whose first unit test run fails",
                state=ProjectState.PLANNING.value,
                max_enrichment_passes=0,
            )
        )
        await session.commit()

    executor = PipelineExecutor()
    executor.workspace = WorkspaceManager(str(tmp_path))
    executor.runner.workspace = executor.workspace
    executor.runner._cloud.workspace = executor.workspace
    executor.runner._cursor_local.workspace = executor.workspace
    executor.test_runner.agent.workspace = executor.workspace

    real_unit_testing = executor._stage_unit_testing
    calls = {"n": 0}

    async def flaky_unit_testing(session, project, context):
        calls["n"] += 1
        if calls["n"] == 1:
            context["last_failure"] = (
                "FAILED tests/test_app.py::test_r1_health - AssertionError: assert 500 == 200"
            )
            return False
        return await real_unit_testing(session, project, context)

    with ExitStack() as stack:
        stack.enter_context(patch("app.pipeline.executor.SessionLocal", session_factory))
        stack.enter_context(patch("app.agents.factory.SessionLocal", session_factory))
        stack.enter_context(patch.object(executor.runner, "docker_available", lambda: False))
        stack.enter_context(patch.object(executor, "_stage_unit_testing", flaky_unit_testing))

        await asyncio.wait_for(executor.run_pipeline(project_id), timeout=600)

    async with session_factory() as session:
        project = await session.get(ProjectRow, project_id)
        assert project.state == ProjectState.REVIEW.value, project.state

        failures = (
            (await session.execute(
                select(FailureRecordRow).where(FailureRecordRow.project_id == project_id)
            )).scalars().all()
        )
        assert len(failures) == 1
        record = failures[0]
        assert record.error_class == "app"
        assert record.gate == ProjectState.IMPLEMENTING.value
        assert record.resolved is True
        assert record.regression_test and record.regression_test.startswith("test_fix_")

        runs = (
            (await session.execute(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
            )).scalars().all()
        )
        assert runs[0].outcome == "completed"
        assert runs[0].fix_attempts == 1
        assert runs[0].gates_failed and runs[0].gates_failed[0]["gate"] == "IMPLEMENTING"

    # The regression-test policy held: the fix pinned the failure on disk.
    repo = WorkspaceManager(str(tmp_path)).repo_dir(project_id)
    regression_tests = list((repo / "tests" / "regression").glob("test_fix_*.py"))
    assert len(regression_tests) == 1


@pytest.mark.asyncio
async def test_infra_failures_retry_without_spending_fix_attempts(pipeline_env, tmp_path):
    """Infra-classified failures use the cheap ladder rung (retry, no developer fix)."""
    from app.db_models import FailureRecordRow
    from app.pipeline.executor import PipelineExecutor
    from app.workspace.manager import WorkspaceManager

    session_factory = pipeline_env
    project_id = uuid4()

    async with session_factory() as session:
        session.add(
            ProjectRow(
                id=project_id,
                name="Infra Flake",
                description="Docker hiccups once during integration",
                state=ProjectState.PLANNING.value,
                max_enrichment_passes=0,
            )
        )
        await session.commit()

    executor = PipelineExecutor()
    executor.workspace = WorkspaceManager(str(tmp_path))
    executor.runner.workspace = executor.workspace
    executor.runner._cloud.workspace = executor.workspace
    executor.runner._cursor_local.workspace = executor.workspace
    executor.test_runner.agent.workspace = executor.workspace

    real_integration = executor._stage_integration_testing
    calls = {"n": 0}

    async def flaky_integration(session, project, context):
        calls["n"] += 1
        if calls["n"] == 1:
            context["last_failure"] = (
                "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
            )
            return False
        return await real_integration(session, project, context)

    with ExitStack() as stack:
        stack.enter_context(patch("app.pipeline.executor.SessionLocal", session_factory))
        stack.enter_context(patch("app.agents.factory.SessionLocal", session_factory))
        stack.enter_context(patch.object(executor.runner, "docker_available", lambda: False))
        stack.enter_context(
            patch.object(executor, "_stage_integration_testing", flaky_integration)
        )

        await asyncio.wait_for(executor.run_pipeline(project_id), timeout=600)

    async with session_factory() as session:
        project = await session.get(ProjectRow, project_id)
        assert project.state == ProjectState.REVIEW.value, project.state

        runs = (
            (await session.execute(
                select(PipelineRunRow).where(PipelineRunRow.project_id == project_id)
            )).scalars().all()
        )
        # The retry consumed an infra retry, not a developer fix attempt.
        assert runs[0].fix_attempts == 0
        assert runs[0].infra_retries == 1

        failures = (
            (await session.execute(
                select(FailureRecordRow).where(FailureRecordRow.project_id == project_id)
            )).scalars().all()
        )
        assert failures[0].error_class == "infra"
