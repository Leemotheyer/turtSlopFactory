import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import CursorConnectionRow, FactorySettingsRow
from app.services.factory_settings import complete_setup, get_setup_status, set_instance_api_key
from app.services.instance_auth import api_key_required, refresh_api_key_cache


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(FactorySettingsRow.__table__.create)
        await conn.run_sync(CursorConnectionRow.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        yield db

    await engine.dispose()


@pytest.mark.asyncio
async def test_setup_status_defaults(session):
    status = await get_setup_status(session)
    assert status["preview_host"]
    assert status["api_url"].startswith("http://")
    assert status["auto_configured"]["encryption_key"] is True


@pytest.mark.asyncio
async def test_complete_setup_marks_done(session):
    status = await complete_setup(session, preview_host="factory.local")
    assert status["setup_complete"] is True
    assert status["preview_host"] == "factory.local"


@pytest.mark.asyncio
async def test_instance_api_key_from_dashboard(session):
    await set_instance_api_key(session, "dashboard-secret")
    await refresh_api_key_cache(session)
    assert api_key_required() is True
