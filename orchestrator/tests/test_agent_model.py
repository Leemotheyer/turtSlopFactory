import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import FactorySettingsRow
from app.services.factory_settings import get_agent_model, set_agent_model


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(FactorySettingsRow.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        yield db

    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_model_defaults_to_env(session):
    model = await get_agent_model(session)
    assert model == "composer-2"


@pytest.mark.asyncio
async def test_set_agent_model_persists(session):
    await set_agent_model(session, "claude-4-sonnet-thinking")
    assert await get_agent_model(session) == "claude-4-sonnet-thinking"


@pytest.mark.asyncio
async def test_set_agent_model_rejects_blank(session):
    with pytest.raises(ValueError):
        await set_agent_model(session, "   ")
