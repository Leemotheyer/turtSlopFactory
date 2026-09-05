from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.services.project_stats import compute_project_stats


@pytest_asyncio.fixture
async def session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_compute_project_stats_sums_active_run_time(session_factory):
    project_id = uuid4()
    async with session_factory() as session:
        from app.db_models import PipelineRunRow, ProjectRow

        session.add(ProjectRow(id=project_id, name="Stats App", description="test"))
        started = datetime.utcnow() - timedelta(hours=2)
        session.add(
            PipelineRunRow(
                project_id=project_id,
                mode="build",
                outcome="completed",
                started_at=started,
                finished_at=started + timedelta(minutes=30),
            )
        )
        session.add(
            PipelineRunRow(
                project_id=project_id,
                mode="post_production",
                outcome="completed",
                started_at=started + timedelta(hours=1),
                finished_at=started + timedelta(hours=1, minutes=20),
            )
        )
        session.add(
            PipelineRunRow(
                project_id=project_id,
                mode="build",
                outcome="stopped",
                started_at=started + timedelta(hours=1, minutes=30),
                finished_at=started + timedelta(hours=1, minutes=45),
            )
        )
        await session.commit()

        with patch("app.services.project_stats.pipeline_executor") as executor, patch(
            "app.services.project_stats.is_pipeline_paused", return_value=False
        ), patch(
            "app.services.project_stats.get_self_propelling_settings",
            return_value={"cycles_completed": 1},
        ):
            executor.is_running.return_value = False
            stats = await compute_project_stats(session, project_id, project_state="PRODUCTION")

    assert stats["development_seconds"] == 30 * 60 + 20 * 60
    assert stats["pipeline_runs_stopped"] == 1
    assert stats["build_cycles"] == 1
    assert stats["improvement_cycles"] == 1
    assert stats["total_cycles"] == 2
    assert stats["post_production_runs"] == 1


@pytest.mark.asyncio
async def test_compute_project_stats_includes_running_pipeline(session_factory):
    project_id = uuid4()
    async with session_factory() as session:
        from app.db_models import PipelineRunRow, ProjectRow

        session.add(ProjectRow(id=project_id, name="Running", description="test"))
        started = datetime.utcnow() - timedelta(minutes=5)
        session.add(
            PipelineRunRow(
                project_id=project_id,
                mode="post_production",
                outcome="running",
                started_at=started,
                finished_at=None,
            )
        )
        await session.commit()

        with patch("app.services.project_stats.pipeline_executor") as executor, patch(
            "app.services.project_stats.is_pipeline_paused", return_value=False
        ), patch(
            "app.services.project_stats.get_self_propelling_settings",
            return_value={"cycles_completed": 0},
        ):
            executor.is_running.return_value = True
            stats = await compute_project_stats(session, project_id)

    assert stats["development_active"] is True
    assert stats["development_seconds"] >= 4 * 60


@pytest.mark.asyncio
async def test_compute_project_stats_waiting_for_production_flag(session_factory):
    project_id = uuid4()
    async with session_factory() as session:
        from app.db_models import ProjectRow

        session.add(ProjectRow(id=project_id, name="Review", description="test"))
        await session.commit()

        with patch("app.services.project_stats.pipeline_executor") as executor, patch(
            "app.services.project_stats.is_pipeline_paused", return_value=False
        ), patch(
            "app.services.project_stats.get_self_propelling_settings",
            return_value={"cycles_completed": 0},
        ):
            executor.is_running.return_value = False
            stats = await compute_project_stats(session, project_id, project_state="REVIEW")

    assert stats["waiting_for_production"] is True
    assert stats["total_cycles"] == 0
