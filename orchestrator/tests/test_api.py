"""HTTP integration tests for core API routes."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.db_models import ProjectRow, TaskRow
from app.main import create_app
from app.models import ProjectState, TaskStatus


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


@pytest.mark.asyncio
async def test_health_returns_ok(api_client):
    client, _ = api_client
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
@patch("app.services.project_lifecycle.stop_preview", new_callable=AsyncMock)
@patch("app.services.project_lifecycle.pipeline_executor.is_running", return_value=False)
@patch("app.api.projects.run_discovery", new_callable=AsyncMock)
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_projects_crud(_mock_publish, mock_discovery, _mock_running, _mock_preview, api_client):
    client, session_factory = api_client
    mock_discovery.return_value = None

    # Create
    create_resp = await client.post(
        "/api/projects",
        json={"name": "Demo App", "description": "A test project"},
    )
    assert create_resp.status_code == 201
    project = create_resp.json()
    project_id = project["id"]
    assert project["name"] == "Demo App"
    assert project["state"] == ProjectState.REQUESTED.value

    # List
    list_resp = await client.get("/api/projects")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Get
    get_resp = await client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == project_id

    # Update
    patch_resp = await client.patch(
        f"/api/projects/{project_id}",
        json={"max_enrichment_passes": 5},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["max_enrichment_passes"] == 5

    # Delete
    delete_resp = await client.delete(f"/api/projects/{project_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "deleted"

    # Get after delete
    gone_resp = await client.get(f"/api/projects/{project_id}")
    assert gone_resp.status_code == 404


@pytest.mark.asyncio
async def test_project_not_found(api_client):
    client, _ = api_client
    missing = uuid4()
    response = await client.get(f"/api/projects/{missing}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


@pytest.mark.asyncio
@patch("app.api.projects.run_discovery", new_callable=AsyncMock)
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_project_create_validation(_mock_publish, _mock_discovery, api_client):
    client, _ = api_client
    response = await client.post("/api/projects", json={"name": "", "description": "x"})
    assert response.status_code == 422


@pytest.mark.asyncio
@patch("app.api.projects.run_discovery", new_callable=AsyncMock)
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_project_invalid_enrichment_passes(_mock_publish, _mock_discovery, api_client):
    client, _ = api_client
    create_resp = await client.post(
        "/api/projects",
        json={"name": "App", "description": "desc"},
    )
    project_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/projects/{project_id}",
        json={"max_enrichment_passes": 99},
    )
    assert response.status_code == 400
    assert "max_enrichment_passes" in response.json()["detail"]


@pytest.mark.asyncio
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_tasks_crud(_mock_publish, api_client):
    client, session_factory = api_client

    async with session_factory() as session:
        project = ProjectRow(name="Task Project", description="For tasks", state=ProjectState.PLANNING.value)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        project_id = project.id

    # Create task
    create_resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"title": "Build API", "description": "Implement endpoints", "role": "developer"},
    )
    assert create_resp.status_code == 201
    task = create_resp.json()
    task_id = task["id"]
    assert task["status"] == TaskStatus.QUEUED.value

    # List project tasks
    list_resp = await client.get(f"/api/projects/{project_id}/tasks")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Get task
    get_resp = await client.get(f"/api/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["title"] == "Build API"

    # Update task via PATCH
    patch_resp = await client.patch(
        f"/api/tasks/{task_id}",
        json={"title": "Build REST API", "status": "RUNNING"},
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["title"] == "Build REST API"
    assert updated["status"] == TaskStatus.RUNNING.value

    # Update status via legacy endpoint
    status_resp = await client.post(f"/api/tasks/{task_id}/status?status=COMPLETED")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == TaskStatus.COMPLETED.value

    # Delete task
    delete_resp = await client.delete(f"/api/tasks/{task_id}")
    assert delete_resp.status_code == 200

    gone_resp = await client.get(f"/api/tasks/{task_id}")
    assert gone_resp.status_code == 404


@pytest.mark.asyncio
async def test_task_not_found(api_client):
    client, _ = api_client
    missing = uuid4()
    response = await client.get(f"/api/tasks/{missing}")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_cannot_delete_running_task(_mock_publish, api_client):
    client, session_factory = api_client

    async with session_factory() as session:
        project = ProjectRow(name="Run Task", description="x", state=ProjectState.IMPLEMENTING.value)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        task = TaskRow(
            project_id=project.id,
            title="Active",
            description="",
            role="developer",
            status=TaskStatus.RUNNING.value,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    response = await client.delete(f"/api/tasks/{task_id}")
    assert response.status_code == 409


@pytest.mark.asyncio
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_create_task_for_missing_project(_mock_publish, api_client):
    client, _ = api_client
    response = await client.post(
        f"/api/projects/{uuid4()}/tasks",
        json={"title": "Orphan", "description": ""},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("app.middleware.get_effective_api_key", return_value="secret-key")
async def test_api_key_middleware(_mock_key, api_client):
    client, _ = api_client

    no_key = await client.get("/api/projects")
    assert no_key.status_code == 401

    with_key = await client.get("/api/projects", headers={"X-API-Key": "secret-key"})
    assert with_key.status_code == 200

    health = await client.get("/health")
    assert health.status_code == 200


@pytest.mark.asyncio
@patch("app.api.projects.event_bus.publish", new_callable=AsyncMock)
async def test_project_advance_and_fail(_mock_publish, api_client):
    client, session_factory = api_client

    async with session_factory() as session:
        project = ProjectRow(
            name="State Machine",
            description="Test transitions",
            state=ProjectState.REQUESTED.value,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        project_id = project.id

    advance_resp = await client.post(f"/api/projects/{project_id}/advance")
    assert advance_resp.status_code == 200
    assert advance_resp.json()["state"] == ProjectState.DISCOVERY.value

    # Cannot advance from PRODUCTION
    async with session_factory() as session:
        row = await session.get(ProjectRow, project_id)
        row.state = ProjectState.PRODUCTION.value
        await session.commit()

    fail_resp = await client.post(f"/api/projects/{project_id}/fail")
    assert fail_resp.status_code == 400


@pytest.mark.asyncio
@patch("app.services.notes.event_bus.publish", new_callable=AsyncMock)
@patch("app.services.feedback_pipeline.maybe_schedule_feedback_pipeline", new_callable=AsyncMock)
async def test_project_notes(_mock_schedule, _mock_publish, api_client):
    client, session_factory = api_client

    async with session_factory() as session:
        project = ProjectRow(name="Notes", description="x", state=ProjectState.REVIEW.value)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        project_id = project.id

    create_resp = await client.post(
        f"/api/projects/{project_id}/notes",
        json={"content": "Add dark mode", "note_type": "feature"},
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["content"] == "Add dark mode"

    list_resp = await client.get(f"/api/projects/{project_id}/notes")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_list_all_tasks(api_client):
    client, session_factory = api_client

    async with session_factory() as session:
        project = ProjectRow(name="All Tasks", description="x", state=ProjectState.PLANNING.value)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        session.add(
            TaskRow(project_id=project.id, title="One", description="", role="developer")
        )
        session.add(
            TaskRow(project_id=project.id, title="Two", description="", role="tester")
        )
        await session.commit()

    response = await client.get("/api/tasks")
    assert response.status_code == 200
    assert len(response.json()) == 2
