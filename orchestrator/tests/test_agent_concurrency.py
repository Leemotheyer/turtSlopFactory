from app.services.agent_concurrency import _is_active_agent_status


def test_reclaim_idle_factory_agents_archives_old_factory_shells():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from app.services.agent_concurrency import reclaim_idle_factory_agents

    client = AsyncMock()
    client.list_agents_page = AsyncMock(
        return_value=(
            [
                {"id": "bc-keep", "name": "factory-architect-new", "status": "ACTIVE", "latestRun": {"status": "FINISHED"}},
                {"id": "bc-old", "name": "factory-developer-old", "status": "ACTIVE", "latestRun": {"status": "FINISHED"}},
                {"id": "bc-busy", "name": "factory-developer-busy", "status": "ACTIVE", "latestRun": {"status": "RUNNING"}},
                {"id": "bc-user", "name": "manual research", "status": "ACTIVE", "latestRun": {"status": "FINISHED"}},
            ],
            None,
        )
    )
    client.archive_agent = AsyncMock(return_value={"id": "bc-old"})
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False

    async def _run():
        with patch("app.services.agent_concurrency.CursorClient", return_value=client):
            archived = await reclaim_idle_factory_agents("key", keep_recent=1)
        assert archived == 1
        client.archive_agent.assert_awaited_once_with("bc-old")

    asyncio.run(_run())


def test_active_agent_status():
    assert _is_active_agent_status("RUNNING") is True
    assert _is_active_agent_status("CREATING") is True
    assert _is_active_agent_status("ACTIVE") is False
    assert _is_active_agent_status("ARCHIVED") is False
    assert _is_active_agent_status("FINISHED") is False
    assert _is_active_agent_status("CANCELLED") is False
    assert _is_active_agent_status("") is False


def test_agent_consumes_slot_with_running_latest_run():
    from app.services.agent_concurrency import agent_consumes_cursor_slot

    assert agent_consumes_cursor_slot({"status": "ACTIVE", "latestRun": {"status": "RUNNING"}}) is True
    assert agent_consumes_cursor_slot({"status": "ACTIVE", "latestRun": {"status": "FINISHED"}}) is False


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
                    return_value=(5, 2, ["a1"]),
                ):
                    budget = await resolve_concurrency_budget(session)
            assert budget.active_cursor_agents == 5
            assert budget.idle_agents == 2
            assert budget.max_parallel == 1
        await engine.dispose()

    asyncio.run(_run())


def test_resolve_concurrency_budget_no_slots_when_full():
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
                    return_value=(7, 5, ["busy"]),
                ):
                    budget = await resolve_concurrency_budget(session)
            assert budget.max_parallel == 0
            assert budget.available_cursor_slots == 0
        await engine.dispose()

    asyncio.run(_run())
