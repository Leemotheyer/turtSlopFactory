from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import EventRow
from app.models import EventType, FactoryEvent

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[FactoryEvent])
async def list_events(
    project_id: UUID | None = None,
    task_id: UUID | None = None,
    limit: int = Query(default=100, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[FactoryEvent]:
    query = select(EventRow).order_by(EventRow.created_at.desc()).limit(limit)
    if project_id:
        query = query.where(EventRow.project_id == project_id)
    if task_id:
        query = query.where(EventRow.task_id == task_id)

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        FactoryEvent(
            id=row.id,
            type=EventType(row.type),
            project_id=row.project_id,
            task_id=row.task_id,
            agent_id=row.agent_id,
            payload=row.payload,
            created_at=row.created_at,
        )
        for row in reversed(rows)
    ]
