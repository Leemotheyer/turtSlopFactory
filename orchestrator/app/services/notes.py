from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectNoteRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, NoteType, ProjectNote, ProjectNoteCreate, ProjectNoteUpdate


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


def _note_from_row(row: ProjectNoteRow) -> ProjectNote:
    return ProjectNote(
        id=row.id,
        project_id=row.project_id,
        content=row.content,
        note_type=NoteType(row.note_type),
        created_at=row.created_at,
    )


async def get_note(session: AsyncSession, project_id: UUID, note_id: UUID) -> ProjectNote | None:
    row = await session.get(ProjectNoteRow, note_id)
    if not row or row.project_id != project_id:
        return None
    return _note_from_row(row)


async def update_note(
    session: AsyncSession,
    project_id: UUID,
    note_id: UUID,
    body: ProjectNoteUpdate,
) -> ProjectNote | None:
    row = await session.get(ProjectNoteRow, note_id)
    if not row or row.project_id != project_id:
        return None

    if body.content is not None:
        row.content = body.content
    if body.note_type is not None:
        row.note_type = body.note_type.value

    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.NOTE_UPDATED,
            project_id=project_id,
            payload={
                "note_id": str(note_id),
                "note_type": row.note_type,
                "content": row.content[:200],
            },
        ),
    )

    return _note_from_row(row)


async def delete_note(session: AsyncSession, project_id: UUID, note_id: UUID) -> bool:
    row = await session.get(ProjectNoteRow, note_id)
    if not row or row.project_id != project_id:
        return False

    note_type = row.note_type
    content_preview = row.content[:200]
    await session.delete(row)
    await session.commit()

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.NOTE_DELETED,
            project_id=project_id,
            payload={"note_id": str(note_id), "note_type": note_type, "content": content_preview},
        ),
    )
    return True


async def list_notes(session: AsyncSession, project_id: UUID) -> list[ProjectNote]:
    result = await session.execute(
        select(ProjectNoteRow)
        .where(ProjectNoteRow.project_id == project_id)
        .order_by(ProjectNoteRow.created_at.desc())
    )
    return [
        _note_from_row(r)
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
