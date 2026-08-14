"""Shared fixtures for API integration tests."""

import os
import tempfile
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

_test_root = tempfile.mkdtemp(prefix="turtslopfactory-test-")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ["WORKSPACE_ROOT"] = _test_root
os.environ["FACTORY_CONFIG_DIR"] = _test_root


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


from app.database import Base, get_db  # noqa: E402


@pytest.fixture
def api_client() -> AsyncGenerator[TestClient, None]:
    """FastAPI TestClient backed by in-memory SQLite and mocked external services."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def init_test_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    with (
        patch("app.main.init_db", side_effect=init_test_db),
        patch("app.main.run_instance_bootstrap", new_callable=AsyncMock),
        patch("app.main.event_bus.connect", new_callable=AsyncMock),
        patch("app.main.event_bus.close", new_callable=AsyncMock),
        patch("app.main.pipeline_queue.connect", new_callable=AsyncMock),
        patch("app.main.pipeline_queue.close", new_callable=AsyncMock),
        patch("app.worker.pipeline_queue.enqueue_discovery", new_callable=AsyncMock),
        patch("app.api.projects.pipeline_queue.enqueue_discovery", new_callable=AsyncMock),
        patch("app.api.projects.setup_project_branches", new_callable=AsyncMock, return_value="ok"),
        patch("app.api.projects.maybe_request_github_token", new_callable=AsyncMock),
        patch("app.events.event_bus.publish", new_callable=AsyncMock, side_effect=lambda _s, e: e),
    ):
        from app.api.items import _reset_items_for_tests
        from app.main import create_app

        _reset_items_for_tests()
        app = create_app()
        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as client:
            yield client

        app.dependency_overrides.clear()

    engine.sync_engine.dispose()
