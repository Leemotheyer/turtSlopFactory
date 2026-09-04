from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.db_models import DeploymentRow, ProjectRow
from app.pipeline.stages.build_deploy import verify_deployment


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


class _FakeExecutor:
    def __init__(self, workspace):
        self.workspace = workspace
        self.deploy_calls: list[str] = []

    async def _deploy_live_preview(self, session, project, context, *, preview_type, image_tag=None, notify=False):
        self.deploy_calls.append(image_tag)
        return True


def _http_response(status_code: int):
    response = MagicMock()
    response.status_code = status_code
    return response


def _mock_client(responses):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=responses)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_healthy_deployment_verified(db, workspace, monkeypatch):
    monkeypatch.setattr(settings, "deploy_observation_seconds", 0)
    monkeypatch.setattr(settings, "deploy_observation_polls", 2)

    project = ProjectRow(id=uuid4(), name="p", description="d")
    db.add(project)
    dep = DeploymentRow(project_id=project.id, environment="staging", image_tag="factory/p:b2", status="running")
    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    ex = _FakeExecutor(workspace)
    context = {
        "preview_backend": "docker",
        "preview_upstream": "http://factory-live-x:8080",
        "preview_health_path": "/health",
        "last_deployment_id": str(dep.id),
    }

    with patch(
        "app.pipeline.stages.build_deploy.httpx.AsyncClient",
        return_value=_mock_client([_http_response(200), _http_response(200)]),
    ):
        ok = await verify_deployment(ex, db, project, context, image_tag="factory/p:b2")

    assert ok is True
    await db.refresh(dep)
    assert dep.verification_status == "verified"
    assert ex.deploy_calls == []


@pytest.mark.asyncio
async def test_unhealthy_deployment_rolls_back_to_previous_tag(db, workspace, monkeypatch):
    monkeypatch.setattr(settings, "deploy_observation_seconds", 0)
    monkeypatch.setattr(settings, "deploy_observation_polls", 2)

    project = ProjectRow(id=uuid4(), name="p", description="d")
    db.add(project)
    # A previous good staging deployment exists.
    db.add(
        DeploymentRow(
            project_id=project.id, environment="staging",
            image_tag="factory/p:b1", status="running",
        )
    )
    dep = DeploymentRow(
        project_id=project.id, environment="staging", image_tag="factory/p:b2", status="running"
    )
    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    ex = _FakeExecutor(workspace)
    context = {
        "preview_backend": "docker",
        "preview_upstream": "http://factory-live-x:8080",
        "preview_health_path": "/health",
        "last_deployment_id": str(dep.id),
    }

    with patch(
        "app.pipeline.stages.build_deploy.httpx.AsyncClient",
        return_value=_mock_client([_http_response(500), _http_response(500)]),
    ):
        ok = await verify_deployment(ex, db, project, context, image_tag="factory/p:b2")

    assert ok is False
    # Rolled back by redeploying the previous tag.
    assert ex.deploy_calls == ["factory/p:b1"]
    await db.refresh(dep)
    assert dep.verification_status == "rolled_back"
    assert "Rolled back" in context["last_failure"]


@pytest.mark.asyncio
async def test_simulated_deploys_skip_verification(db, workspace):
    project = ProjectRow(id=uuid4(), name="p", description="d")
    db.add(project)
    await db.commit()
    ex = _FakeExecutor(workspace)
    context = {"preview_backend": "simulated"}
    ok = await verify_deployment(ex, db, project, context, image_tag="factory/p:b1")
    assert ok is True
