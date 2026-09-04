import pytest
from sqlalchemy import JSON, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from app.migrations import MIGRATIONS, run_migrations


def _swap_jsonb():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.mark.asyncio
async def test_migrations_apply_once_and_record(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m.db")
    _swap_jsonb()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    applied = await run_migrations(engine)
    assert applied == [m[0] for m in MIGRATIONS]

    # Second run is a no-op.
    applied_again = await run_migrations(engine)
    assert applied_again == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_gate_realignment_shifts_legacy_states(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "ws"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/m2.db")
    _swap_jsonb()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Simulate legacy rows persisted before the realignment.
        for i, legacy in enumerate(
            ["UNIT_TESTING", "INTEGRATION_TESTING", "DOCKER_BUILD", "STAGING_DEPLOY", "REVIEW"]
        ):
            await conn.execute(
                text(
                    "INSERT INTO projects (id, name, description, state, branch, base_branch, isolate_branch, created_at, updated_at) "
                    f"VALUES ('00000000-0000-0000-0000-00000000000{i}', 'p{i}', 'd', :state, 'main', 'main', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"state": legacy},
            )

    await run_migrations(engine)

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name, state FROM projects ORDER BY name"))
        states = dict(result.fetchall())

    # Old states shift one gate forward; REVIEW is unchanged.
    assert states["p0"] == "INTEGRATION_TESTING"  # was UNIT_TESTING
    assert states["p1"] == "DOCKER_BUILD"  # was INTEGRATION_TESTING
    assert states["p2"] == "STAGING_DEPLOY"  # was DOCKER_BUILD
    assert states["p3"] == "SMOKE_TESTING"  # was STAGING_DEPLOY
    assert states["p4"] == "REVIEW"
    await engine.dispose()
