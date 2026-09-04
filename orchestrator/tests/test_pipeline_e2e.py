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
