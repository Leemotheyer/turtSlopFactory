import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import FactorySettingsRow
from app.services.factory_settings import (
    get_agent_model,
    get_agent_model_for_role,
    get_agent_models,
    set_agent_model,
    set_agent_models,
)


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
    models = await get_agent_models(session)
    assert models == {
        "architect": "composer-2",
        "developer": "composer-2",
        "reviewer": "composer-2",
    }


@pytest.mark.asyncio
async def test_set_agent_model_sets_all_roles(session):
    await set_agent_model(session, "claude-4-sonnet-thinking")
    models = await get_agent_models(session)
    assert models == {
        "architect": "claude-4-sonnet-thinking",
        "developer": "claude-4-sonnet-thinking",
        "reviewer": "claude-4-sonnet-thinking",
    }


@pytest.mark.asyncio
async def test_set_agent_models_per_role(session):
    await set_agent_models(
        session,
        {
            "architect": "claude-4-sonnet-thinking",
            "developer": "composer-2.5",
            "reviewer": "gpt-5.4-medium",
        },
    )
    assert await get_agent_model_for_role(session, "architect") == "claude-4-sonnet-thinking"
    assert await get_agent_model_for_role(session, "developer") == "composer-2.5"
    assert await get_agent_model_for_role(session, "reviewer") == "gpt-5.4-medium"


@pytest.mark.asyncio
async def test_set_agent_model_rejects_blank(session):
    with pytest.raises(ValueError):
        await set_agent_model(session, "   ")
