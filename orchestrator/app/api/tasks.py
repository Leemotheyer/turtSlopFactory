from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import EventRow, TaskRow
from app.events import event_bus
from app.models import AgentRole, EventType, FactoryEvent, Task, TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_from_row(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        description=row.description,
        role=AgentRole(row.role),
        status=TaskStatus(row.status),
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[Task])
async def list_all_tasks(db: AsyncSession = Depends(get_db)) -> list[Task]:
    result = await db.execute(select(TaskRow).order_by(TaskRow.created_at.desc()))
    return [_task_from_row(row) for row in result.scalars()]


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: UUID, db: AsyncSession = Depends(get_db)) -> Task:
    row = await db.get(TaskRow, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_from_row(row)


@router.post("/{task_id}/status", response_model=Task)
async def update_status(
    task_id: UUID, status: TaskStatus, db: AsyncSession = Depends(get_db)
) -> Task:
    row = await db.get(TaskRow, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    previous = row.status
    row.status = status.value
    await db.commit()
    await db.refresh(row)

    await event_bus.publish(
        db,
        FactoryEvent(
            type=EventType.TASK_STATUS_CHANGED,
            project_id=row.project_id,
            task_id=row.id,
            payload={"from": previous, "to": status.value, "title": row.title},
        ),
    )

    return _task_from_row(row)
