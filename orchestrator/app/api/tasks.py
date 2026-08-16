from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import EventRow, TaskRow
from app.events import event_bus
from app.models import AgentRole, EventType, FactoryEvent, Task, TaskStatus, TaskUpdate

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


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    task_id: UUID, body: TaskUpdate, db: AsyncSession = Depends(get_db)
) -> Task:
    row = await db.get(TaskRow, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    previous_status = row.status
    changed = False

    if body.title is not None:
        row.title = body.title
        changed = True
    if body.description is not None:
        row.description = body.description
        changed = True
    if body.status is not None:
        row.status = body.status.value
        changed = True

    if not changed:
        raise HTTPException(status_code=400, detail="No fields to update")

    await db.commit()
    await db.refresh(row)

    if body.status is not None and body.status.value != previous_status:
        await event_bus.publish(
            db,
            FactoryEvent(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=row.project_id,
                task_id=row.id,
                payload={"from": previous_status, "to": body.status.value, "title": row.title},
            ),
        )

    return _task_from_row(row)


@router.delete("/{task_id}")
async def delete_task(task_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(TaskRow, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    if row.status == TaskStatus.RUNNING.value:
        raise HTTPException(status_code=409, detail="Cannot delete a running task")

    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "task_id": str(task_id)}


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
