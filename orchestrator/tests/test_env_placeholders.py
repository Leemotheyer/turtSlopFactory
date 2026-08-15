from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import EnvRequirementRow, NotificationRow, ProjectRow, ProjectSecretRow
from app.services.secrets import ensure_env_placeholder, list_secrets_public


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in (
            ProjectRow.__table__,
            ProjectSecretRow.__table__,
            EnvRequirementRow.__table__,
            NotificationRow.__table__,
        ):
            await conn.run_sync(table.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project = ProjectRow(name="Test", description="Komga login app")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        yield session, project.id

    await engine.dispose()


@pytest.mark.asyncio
@patch("app.services.secrets.event_bus.publish", new_callable=AsyncMock)
@patch("app.services.secrets.create_notification", new_callable=AsyncMock)
async def test_ensure_env_placeholder_creates_empty_secret(_notif, _publish, db_session):
    session, project_id = db_session
    await ensure_env_placeholder(
        session,
        project_id,
        "KOMGA_BASE_URL",
        "Komga server URL",
        requested_by="factory",
    )
    public = await list_secrets_public(session, project_id)
    komga = next(s for s in public["secrets"] if s["key_name"] == "KOMGA_BASE_URL")
    assert komga["needs_value"] is True
    assert komga["configured"] is False
    assert any(r["key_name"] == "KOMGA_BASE_URL" for r in public["pending_requirements"])
