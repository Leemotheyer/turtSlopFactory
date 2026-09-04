from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.db_models import InputRequestRow, ProjectRow
from app.services.input_requests import create_input_request, expire_stale_requests


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_normal_requests_auto_resolve_after_expiry(db):
    project = ProjectRow(id=uuid4(), name="p", description="d")
    db.add(project)
    await db.commit()

    request = await create_input_request(
        db, project.id, agent_id="a", role="developer",
        question="Storage choice?", default_decision="In-memory",
    )
    row = await db.get(InputRequestRow, request.id)
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()

    resolved = await expire_stale_requests(db)
    assert resolved == 1
    await db.refresh(row)
    assert row.status == "auto_resolved"


@pytest.mark.asyncio
async def test_destructive_requests_never_auto_resolve(db):
    project = ProjectRow(id=uuid4(), name="p", description="d")
    db.add(project)
    await db.commit()

    request = await create_input_request(
        db, project.id, agent_id="pipeline", role="reviewer",
        question="Merge factory branch into main now?",
        default_decision="Keep on factory branch for now",
        risk="destructive",
    )
    row = await db.get(InputRequestRow, request.id)
    assert row.risk == "destructive"

    # Even with a past expiry, destructive requests wait for a human.
    row.expires_at = datetime.utcnow() - timedelta(days=1)
    await db.commit()
    resolved = await expire_stale_requests(db)
    assert resolved == 0
    await db.refresh(row)
    assert row.status == "open"
