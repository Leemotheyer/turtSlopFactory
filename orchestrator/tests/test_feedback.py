from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db_models import ProgressEntryRow, ProjectNoteRow, ProjectRow
from app.models import NoteType, ProjectNoteCreate
from app.services.notes import add_note, list_notes
from app.services.progress import get_progress_digest, record_progress


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        for table in (ProjectRow.__table__, ProjectNoteRow.__table__, ProgressEntryRow.__table__):
            await conn.run_sync(table.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project = ProjectRow(name="Test", description="Test project")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        yield session, project.id

    await engine.dispose()


@pytest.mark.asyncio
@patch("app.services.notes.event_bus.publish", new_callable=AsyncMock)
async def test_add_and_list_notes(_mock_publish, db_session):
    session, project_id = db_session
    await add_note(session, project_id, ProjectNoteCreate(content="No auth please", note_type=NoteType.SCOPE_OUT))
    notes = await list_notes(session, project_id)
    assert len(notes) == 1
    assert notes[0].content == "No auth please"
    assert notes[0].note_type == NoteType.SCOPE_OUT


@pytest.mark.asyncio
@patch("app.services.progress.event_bus.publish", new_callable=AsyncMock)
async def test_record_progress_digest(_mock_publish, db_session):
    session, project_id = db_session
    await record_progress(session, project_id, "planning", "Planned", "Architecture done")
    digest = await get_progress_digest(session, project_id, "PLANNING", True)
    assert len(digest.entries) == 1
    assert "Planned" in digest.summary_lines[0]


def test_input_request_status_enum():
    from app.models import InputRequestStatus

    assert InputRequestStatus.OPEN.value == "open"
    assert InputRequestStatus.AUTO_RESOLVED.value == "auto_resolved"
