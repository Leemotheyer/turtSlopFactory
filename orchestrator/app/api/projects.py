from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.db_models import ProjectRow, TaskRow
from app.events import event_bus
from app.models import (
    AgentRole,
    DiscoveryStatus,
    EventType,
    FactoryEvent,
    Project,
    ProjectCreate,
    ProjectState,
    Task,
    TaskCreate,
    TaskStatus,
)
from app.worker import pipeline_queue
from app.state_machine import StateMachineError, advance_project, fail_project
from app.workspace.manager import WorkspaceManager

router = APIRouter(prefix="/projects", tags=["projects"])
workspace = WorkspaceManager()


def _project_from_row(row: ProjectRow, preview_url: str | None = None) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        description=row.description,
        repo_url=row.repo_url,
        state=ProjectState(row.state),
        branch=row.branch,
        image_tag=row.image_tag,
        preview_url=preview_url,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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


@router.get("", response_model=list[Project])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[Project]:
    result = await db.execute(select(ProjectRow).order_by(ProjectRow.created_at.desc()))
    projects = []
    for row in result.scalars():
        meta = workspace.load_metadata(row.id)
        preview_url = meta.get("preview_url") or meta.get("staging_url")
        projects.append(_project_from_row(row, preview_url=preview_url))
    return projects


@router.post("", response_model=Project, status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    row = ProjectRow(
        name=body.name,
        description=body.description,
        repo_url=body.repo_url,
        state=ProjectState.REQUESTED.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await event_bus.publish(
        db,
        FactoryEvent(
            type=EventType.STATE_TRANSITION,
            project_id=row.id,
            payload={"from": None, "to": ProjectState.REQUESTED.value, "action": "created"},
        ),
    )

    await pipeline_queue.enqueue_discovery(row.id)

    return _project_from_row(row)


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Project:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_from_row(row)


@router.post("/{project_id}/advance", response_model=Project)
async def advance_state(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Project:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    current = ProjectState(row.state)
    try:
        next_state = advance_project(current)
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row.state = next_state.value
    await db.commit()
    await db.refresh(row)

    await event_bus.publish(
        db,
        FactoryEvent(
            type=EventType.STATE_TRANSITION,
            project_id=row.id,
            payload={"from": current.value, "to": next_state.value},
        ),
    )

    return _project_from_row(row)


@router.post("/{project_id}/fail", response_model=Project)
async def mark_failed(project_id: UUID, db: AsyncSession = Depends(get_db)) -> Project:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    current = ProjectState(row.state)
    try:
        next_state = fail_project(current)
    except StateMachineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row.state = next_state.value
    await db.commit()
    await db.refresh(row)

    await event_bus.publish(
        db,
        FactoryEvent(
            type=EventType.STATE_TRANSITION,
            project_id=row.id,
            payload={"from": current.value, "to": next_state.value, "reason": "gate_failed"},
        ),
    )

    return _project_from_row(row)


@router.get("/{project_id}/tasks", response_model=list[Task])
async def list_tasks(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[Task]:
    result = await db.execute(
        select(TaskRow).where(TaskRow.project_id == project_id).order_by(TaskRow.created_at.desc())
    )
    return [_task_from_row(row) for row in result.scalars()]


@router.post("/{project_id}/tasks", response_model=Task, status_code=201)
async def create_task(
    project_id: UUID, body: TaskCreate, db: AsyncSession = Depends(get_db)
) -> Task:
    project = await db.get(ProjectRow, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    row = TaskRow(
        project_id=project_id,
        title=body.title,
        description=body.description,
        role=body.role.value,
        status=TaskStatus.QUEUED.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    await event_bus.publish(
        db,
        FactoryEvent(
            type=EventType.TASK_STATUS_CHANGED,
            project_id=project_id,
            task_id=row.id,
            payload={"status": TaskStatus.QUEUED.value, "title": row.title},
        ),
    )

    return _task_from_row(row)
