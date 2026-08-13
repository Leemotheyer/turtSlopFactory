from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectNoteRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, NoteType, ProjectNote, ProjectNoteCreate


async def add_note(
    session: AsyncSession,
    project_id: UUID,
    body: ProjectNoteCreate,
) -> ProjectNote:
    row = ProjectNoteRow(
        project_id=project_id,
        content=body.content,
        note_type=body.note_type.value,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.NOTE_ADDED,
            project_id=project_id,
            payload={"note_type": body.note_type.value, "content": body.content[:200]},
        ),
    )

    return ProjectNote(
        id=row.id,
        project_id=row.project_id,
        content=row.content,
        note_type=NoteType(row.note_type),
        created_at=row.created_at,
    )


async def list_notes(session: AsyncSession, project_id: UUID) -> list[ProjectNote]:
    result = await session.execute(
        select(ProjectNoteRow)
        .where(ProjectNoteRow.project_id == project_id)
        .order_by(ProjectNoteRow.created_at.desc())
    )
    return [
        ProjectNote(
            id=r.id,
            project_id=r.project_id,
            content=r.content,
            note_type=NoteType(r.note_type),
            created_at=r.created_at,
        )
        for r in result.scalars()
    ]


async def get_notes_for_agents(session: AsyncSession, project_id: UUID) -> list[dict]:
    """Format notes as context for agent runners."""
    notes = await list_notes(session, project_id)
    return [
        {
            "type": n.note_type.value,
            "content": n.content,
            "created_at": n.created_at.isoformat(),
        }
        for n in notes
    ]
