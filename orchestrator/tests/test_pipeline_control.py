import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import ProjectRow, TaskRow


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in (ProjectRow.__table__, TaskRow.__table__):
            await conn.run_sync(table.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project = ProjectRow(name="Test", description="App")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        yield session, project.id

    await engine.dispose()
