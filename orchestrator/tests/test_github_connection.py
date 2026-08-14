from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import FactorySettingsRow
from app.services.github_connection import (
    connect_github_token,
    disconnect_github_token,
    get_github_connection_status,
    verify_github_token,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(FactorySettingsRow.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
@patch("app.services.github_connection.httpx.AsyncClient")
async def test_verify_and_connect_github(mock_client_cls, db_session):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"login": "devuser", "name": "Dev User"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    profile = await verify_github_token("ghp_test_token")
    assert profile["login"] == "devuser"

    status = await connect_github_token(db_session, "ghp_test_token")
    assert status["connected"] is True
    assert status["verified"] is True
    assert status["github_login"] == "devuser"
    assert "saved" in status["message"]

    stored = await get_github_connection_status(db_session)
    assert stored["connected"] is True
    assert stored["github_login"] == "devuser"
    assert stored["masked_github_token"].endswith("****")

    disconnected = await disconnect_github_token(db_session)
    assert disconnected["connected"] is False

    final = await get_github_connection_status(db_session)
    assert final["connected"] is False
