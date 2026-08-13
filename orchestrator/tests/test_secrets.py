from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import EnvRequirementRow, NotificationRow, ProjectRow, ProjectSecretRow
from app.models import NotificationType
from app.services.crypto import decrypt_value, encrypt_value, mask_value
from app.services.notifications import count_unread, create_notification, list_notifications, mark_read
from app.services.secrets import (
    get_env_status_for_agents,
    list_secrets_public,
    request_env_var,
    set_secret,
)


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
        project = ProjectRow(name="Test", description="Uses OpenAI API")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        yield session, project.id

    await engine.dispose()


def test_encrypt_decrypt_roundtrip():
    plain = "sk-test-secret-key-12345"
    encrypted = encrypt_value(plain)
    assert encrypted != plain
    assert decrypt_value(encrypted) == plain


def test_mask_value():
    assert mask_value("ab") == "****"
    assert mask_value("abcdefghij") == "ab****ij"


@pytest.mark.asyncio
@patch("app.services.secrets.event_bus.publish", new_callable=AsyncMock)
@patch("app.services.notifications.event_bus.publish", new_callable=AsyncMock)
async def test_request_env_var_creates_notification(_notif_publish, _secret_publish, db_session):
    session, project_id = db_session
    row = await request_env_var(session, project_id, "OPENAI_API_KEY", "OpenAI key needed")
    assert row.key_name == "OPENAI_API_KEY"
    assert row.status == "pending"

    status = await get_env_status_for_agents(session, project_id)
    assert "OPENAI_API_KEY" in status["missing_keys"]
    assert status["configured_keys"] == []

    notifs = await list_notifications(session)
    assert any(n.type == NotificationType.ENV_REQUIRED for n in notifs)


@pytest.mark.asyncio
@patch("app.services.secrets.event_bus.publish", new_callable=AsyncMock)
async def test_set_secret_fulfills_requirement(_publish, db_session):
    session, project_id = db_session
    await request_env_var(session, project_id, "API_KEY", "Generic key")
    await set_secret(session, project_id, "API_KEY", "super-secret-value", "Test key")

    public = await list_secrets_public(session, project_id)
    assert len(public["secrets"]) == 1
    assert public["secrets"][0]["key_name"] == "API_KEY"
    assert "****" in public["secrets"][0]["masked_value"]
    assert public["pending_requirements"] == []

    status = await get_env_status_for_agents(session, project_id)
    assert "API_KEY" in status["configured_keys"]
    assert status["missing_keys"] == []


@pytest.mark.asyncio
@patch("app.services.notifications.event_bus.publish", new_callable=AsyncMock)
async def test_notification_read_state(_publish, db_session):
    session, project_id = db_session
    notif = await create_notification(
        session,
        project_id,
        NotificationType.PROJECT_FINISHED,
        "Project complete",
        "Your build finished successfully.",
    )
    assert await count_unread(session) == 1
    assert await mark_read(session, notif.id)
    assert await count_unread(session) == 0
