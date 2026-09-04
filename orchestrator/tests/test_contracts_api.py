"""HTTP tests for contract / requirements / metrics endpoints."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.db_models import PipelineRunRow, ProjectRow
from app.main import create_app
from app.models import ProjectState


@pytest_asyncio.fixture
async def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def test_lifespan(_app):
        yield

    app = create_app()
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory

    await engine.dispose()


_CONTRACT_BODY = {
    "goal": "Track items",
    "requirements": [
        {"id": "R1", "description": "Health endpoint", "acceptance": ["GET /health 200"]},
        {"id": "R2", "description": "Items API", "acceptance": ["CRUD works"]},
    ],
}


async def _make_project(session_factory, state=ProjectState.PLANNING) -> str:
    async with session_factory() as session:
        row = ProjectRow(id=uuid4(), name="P", description="D", state=state.value)
        session.add(row)
        await session.commit()
        return str(row.id)


@pytest.mark.asyncio
async def test_contract_missing_returns_null(api_client):
    client, session_factory = api_client
    project_id = await _make_project(session_factory)
    response = await client.get(f"/api/projects/{project_id}/contract")
    assert response.status_code == 200
    assert response.json()["contract"] is None


@pytest.mark.asyncio
async def test_put_contract_creates_version_and_requirements(api_client):
    client, session_factory = api_client
    project_id = await _make_project(session_factory)

    response = await client.put(f"/api/projects/{project_id}/contract", json=_CONTRACT_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["source"] == "human"

    response = await client.get(f"/api/projects/{project_id}/requirements")
    assert response.status_code == 200
    data = response.json()
    assert [r["req_id"] for r in data["requirements"]] == ["R1", "R2"]
    assert data["health"]["total_requirements"] == 2

    # Editing again bumps the version.
    edited = dict(_CONTRACT_BODY)
    edited["goal"] = "Track items better"
    response = await client.put(f"/api/projects/{project_id}/contract", json=edited)
    assert response.json()["version"] == 2


@pytest.mark.asyncio
async def test_put_contract_rejects_empty_requirements(api_client):
    client, session_factory = api_client
    project_id = await _make_project(session_factory)
    response = await client.put(
        f"/api/projects/{project_id}/contract", json={"goal": "x", "requirements": []}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_waive_and_unwaive_requirement(api_client):
    client, session_factory = api_client
    project_id = await _make_project(session_factory)
    await client.put(f"/api/projects/{project_id}/contract", json=_CONTRACT_BODY)

    response = await client.post(f"/api/projects/{project_id}/requirements/r2/waive")
    assert response.status_code == 200
    assert response.json()["status"] == "waived"

    response = await client.get(f"/api/projects/{project_id}/requirements")
    statuses = {r["req_id"]: r["status"] for r in response.json()["requirements"]}
    assert statuses["R2"] == "waived"

    response = await client.post(f"/api/projects/{project_id}/requirements/R2/unwaive")
    assert response.status_code == 200

    response = await client.post(f"/api/projects/{project_id}/requirements/R99/waive")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_factory_metrics_aggregates_runs(api_client):
    client, session_factory = api_client
    project_id = await _make_project(session_factory)

    from datetime import datetime, timedelta
    from uuid import UUID

    async with session_factory() as session:
        started = datetime.utcnow() - timedelta(minutes=10)
        session.add(
            PipelineRunRow(
                project_id=UUID(project_id), mode="build", outcome="completed",
                started_at=started, finished_at=started + timedelta(minutes=8),
                fix_attempts=2, human_interventions=1,
            )
        )
        session.add(
            PipelineRunRow(
                project_id=UUID(project_id), mode="build", outcome="blocked",
                started_at=started, finished_at=started + timedelta(minutes=5),
                fix_attempts=5,
            )
        )
        await session.commit()

    response = await client.get("/api/metrics/factory")
    assert response.status_code == 200
    data = response.json()
    assert data["runs_completed"] == 1
    assert data["runs_blocked"] == 1
    assert data["success_rate"] == 0.5
    assert data["avg_fix_attempts_per_run"] == 3.5
    assert len(data["recent_runs"]) == 2
