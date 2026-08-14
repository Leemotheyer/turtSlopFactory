from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import CursorConnectionRow
from app.services.cursor_client import CursorUsageSummary
from app.services.cursor_connection import connect_cursor, disconnect_cursor, get_connection_status


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(CursorConnectionRow.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
@patch("app.services.cursor_connection.CursorClient")
async def test_connect_and_disconnect(mock_client_cls, db_session):
    mock_client = MagicMock()
    mock_client.get_me = AsyncMock(
        return_value={
            "apiKeyName": "Factory",
            "userEmail": "dev@example.com",
            "userId": 1,
        }
    )
    mock_client.build_usage_summary = AsyncMock(
        return_value=CursorUsageSummary(connected=True, enterprise_billing=False)
    )
    mock_client.list_models = AsyncMock(return_value=[{"id": "composer-2"}, {"id": "gpt-4"}])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    status = await connect_cursor(db_session, "crsr_test_key")
    assert status["connected"] is True
    assert status["user_email"] == "dev@example.com"
    assert status["verified"] is True
    assert status["models_available"] == 2
    assert "saved securely" in status["message"]

    disconnected = await disconnect_cursor(db_session)
    assert disconnected["connected"] is False

    final = await get_connection_status(db_session)
    assert final["connected"] is False
