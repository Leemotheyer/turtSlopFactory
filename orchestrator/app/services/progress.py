from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProgressEntryRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, ProgressDigest, ProgressEntry


async def record_progress(
    session: AsyncSession,
    project_id: UUID,
    category: str,
    title: str,
    summary: str,
    detail: str | None = None,
) -> ProgressEntryRow:
    row = ProgressEntryRow(
        project_id=project_id,
        category=category,
        title=title,
        summary=summary,
        detail=detail,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.PROGRESS_UPDATED,
            project_id=project_id,
            payload={"category": category, "title": title, "summary": summary},
        ),
    )
    return row


async def get_progress_digest(
    session: AsyncSession,
    project_id: UUID,
    current_state: str,
    pipeline_running: bool,
) -> ProgressDigest:
    result = await session.execute(
        select(ProgressEntryRow)
        .where(ProgressEntryRow.project_id == project_id)
        .order_by(ProgressEntryRow.created_at.asc())
    )
    entries = [
        ProgressEntry(
            id=r.id,
            project_id=r.project_id,
            category=r.category,
            title=r.title,
            summary=r.summary,
            detail=r.detail,
            created_at=r.created_at,
        )
        for r in result.scalars()
    ]

    summary_lines = [f"✓ {e.title}: {e.summary}" for e in entries[-12:]]
    if pipeline_running and entries:
        summary_lines.append(f"→ Currently in {current_state.replace('_', ' ').lower()}")

    return ProgressDigest(
        project_id=project_id,
        current_state=current_state,
        pipeline_running=pipeline_running,
        entries=entries,
        summary_lines=summary_lines,
    )
