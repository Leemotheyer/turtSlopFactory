from app.services.agent_concurrency import _is_active_agent_status


def test_active_agent_status():
    assert _is_active_agent_status("RUNNING") is True
    assert _is_active_agent_status("CREATING") is True
    assert _is_active_agent_status("FINISHED") is False
    assert _is_active_agent_status("CANCELLED") is False
    assert _is_active_agent_status("") is False


def test_resolve_concurrency_budget_local():
    import pytest

    pytest.importorskip("asyncio")
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db_models import FactorySettingsRow
    from app.services.agent_concurrency import resolve_concurrency_budget
    from app.services.factory_settings import set_agent_backend

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(FactorySettingsRow.__table__.create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await set_agent_backend(session, "local")
            budget = await resolve_concurrency_budget(session)
            assert budget.max_parallel >= 1
            assert budget.backend == "local"
        await engine.dispose()

    asyncio.run(_run())


def test_resolve_concurrency_budget_cursor_cloud():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db_models import FactorySettingsRow
    from app.services.agent_concurrency import resolve_concurrency_budget
    from app.services.factory_settings import set_agent_backend

    async def _run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(FactorySettingsRow.__table__.create)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await set_agent_backend(session, "cursor_cloud")
            with patch(
                "app.services.agent_concurrency.get_api_key",
                new_callable=AsyncMock,
                return_value="test-key",
            ):
                with patch(
                    "app.services.agent_concurrency.count_active_cursor_agents",
                    new_callable=AsyncMock,
                    return_value=5,
                ):
                    budget = await resolve_concurrency_budget(session)
            assert budget.active_cursor_agents == 5
            assert budget.max_parallel == 1
        await engine.dispose()

    asyncio.run(_run())
