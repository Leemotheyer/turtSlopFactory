import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.db_models import (
    EvidenceRow,
    PipelineRunRow,
    ProjectContractRow,
    ProjectRow,
    RequirementRow,
)
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


@pytest.mark.asyncio
@patch("app.services.project_lifecycle.pipeline_executor.is_running", return_value=False)
@patch("app.services.project_lifecycle.stop_preview", new_callable=AsyncMock)
async def test_delete_project_with_contract_and_pipeline_runs(_stop, _running):
    """Projects with metrics/contract rows must delete cleanly (PostgreSQL FK enforcement)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    project_id = uuid4()
    async with session_factory() as session:
        session.add(ProjectRow(id=project_id, name="Heavy", description="Has history"))
        session.add(
            ProjectContractRow(project_id=project_id, version=1, data={"goal": "Ship it"})
        )
        req = RequirementRow(project_id=project_id, req_id="R1", description="Works")
        session.add(req)
        await session.flush()
        session.add(
            EvidenceRow(
                project_id=project_id,
                requirement_id=req.id,
                kind="test_run",
                reference="tests/test_r1.py",
            )
        )
        started = datetime.utcnow()
        session.add(
            PipelineRunRow(
                project_id=project_id,
                mode="build",
                outcome="completed",
                started_at=started,
                finished_at=started,
            )
        )
        await session.commit()

    with tempfile.TemporaryDirectory() as tmp:
        ws = WorkspaceManager(root=tmp)
        ws.project_dir(project_id)
        marker = ws.project_dir(project_id) / "marker.txt"
        marker.write_text("local", encoding="utf-8")

        async with session_factory() as session:
            await delete_project(session, project_id, workspace=ws)

        async with session_factory() as session:
            assert await session.get(ProjectRow, project_id) is None
            contracts = await session.execute(
                ProjectContractRow.__table__.select().where(
                    ProjectContractRow.project_id == project_id
                )
            )
            assert contracts.first() is None

        assert not marker.exists()

    await engine.dispose()
