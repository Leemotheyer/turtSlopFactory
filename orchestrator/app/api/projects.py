from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
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
    ProjectUpdate,
    Task,
    TaskCreate,
    TaskStatus,
)
from app.services.discovery import run_discovery
from app.services.git_branching import apply_isolated_branch_fields, setup_project_branches
from app.services.project_lifecycle import delete_project as delete_project_record
from app.services.preview import preview_from_metadata
from app.services.factory_settings import get_preview_origin
from app.services.secrets import get_github_token, maybe_request_github_token
from app.workspace.provisioner import normalize_repo_url
from app.pipeline.executor import pipeline_executor
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
        base_branch=row.base_branch or "main",
        work_branch=row.work_branch,
        isolate_branch=bool(row.isolate_branch),
        merge_status=row.merge_status,
        image_tag=row.image_tag,
        max_enrichment_passes=row.max_enrichment_passes,
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
async def list_projects(request: Request, db: AsyncSession = Depends(get_db)) -> list[Project]:
    origin = await get_preview_origin(db, request)
    result = await db.execute(select(ProjectRow).order_by(ProjectRow.created_at.desc()))
    projects = []
    for row in result.scalars():
        meta = workspace.load_metadata(row.id)
        preview_url = preview_from_metadata(meta, origin=origin, project_id=row.id)["preview_url"]
        projects.append(_project_from_row(row, preview_url=preview_url))
    return projects


@router.post("", response_model=Project, status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)) -> Project:
    repo_url = None
    if body.repo_url:
        try:
            repo_url = normalize_repo_url(body.repo_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    base = (body.base_branch or body.branch or "main").strip() or "main"
    row = ProjectRow(
        name=body.name,
        description=body.description,
        repo_url=repo_url,
        branch=base,
        base_branch=base,
        isolate_branch=body.isolate_branch if repo_url else False,
        merge_status="pending" if repo_url and body.isolate_branch else None,
        max_enrichment_passes=body.max_enrichment_passes,
        state=ProjectState.REQUESTED.value,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    if repo_url:
        apply_isolated_branch_fields(row)
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

    try:
        await run_discovery(db, row.id)
    except Exception as exc:
        workspace.append_log(row.id, "pipeline.log", f"[discovery] Failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Discovery failed: {exc}") from exc

    if repo_url:
        message = await setup_project_branches(
            workspace,
            row,
            github_token=await get_github_token(db, row.id),
        )
        await db.commit()
        workspace.append_log(row.id, "pipeline.log", f"[setup] {message}")
        await maybe_request_github_token(db, row.id, message)

    await db.refresh(row)
    return _project_from_row(row)


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: UUID, request: Request, db: AsyncSession = Depends(get_db)) -> Project:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    origin = await get_preview_origin(db, request)
    meta = workspace.load_metadata(project_id)
    preview_url = preview_from_metadata(meta, origin=origin, project_id=project_id)["preview_url"]
    return _project_from_row(row, preview_url=preview_url)


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    project_id: UUID, body: ProjectUpdate, request: Request, db: AsyncSession = Depends(get_db)
) -> Project:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_changed = False
    branch_settings_changed = False
    prev_repo = row.repo_url
    prev_isolate = row.isolate_branch
    prev_base = row.base_branch
    prev_branch = row.branch
    prev_work = row.work_branch

    if body.clear_repo:
        row.repo_url = None
        repo_changed = True
    elif body.repo_url is not None:
        if not body.repo_url.strip():
            if row.repo_url is not None:
                row.repo_url = None
                repo_changed = True
        else:
            try:
                new_url = normalize_repo_url(body.repo_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if new_url != row.repo_url:
                row.repo_url = new_url
                repo_changed = True

    if body.base_branch is not None:
        new_base = body.base_branch.strip() or "main"
        if new_base != row.base_branch:
            row.base_branch = new_base
            branch_settings_changed = True

    if body.branch is not None:
        new_branch = body.branch.strip() or "main"
        if new_branch != row.branch:
            row.branch = new_branch
            branch_settings_changed = True

    if body.work_branch is not None:
        new_work = body.work_branch.strip() or None
        if new_work != row.work_branch:
            row.work_branch = new_work
            branch_settings_changed = True

    if body.isolate_branch is not None and body.isolate_branch != row.isolate_branch:
        row.isolate_branch = body.isolate_branch
        branch_settings_changed = True

    if body.max_enrichment_passes is not None:
        passes = body.max_enrichment_passes
        if passes < 0 or passes > 20:
            raise HTTPException(status_code=400, detail="max_enrichment_passes must be between 0 and 20")
        row.max_enrichment_passes = passes

    if (
        repo_changed
        or branch_settings_changed
        or prev_repo != row.repo_url
        or prev_isolate != row.isolate_branch
        or prev_base != row.base_branch
        or prev_branch != row.branch
        or prev_work != row.work_branch
    ):
        apply_isolated_branch_fields(row)
        if repo_changed and row.repo_url and row.isolate_branch and row.merge_status is None:
            row.merge_status = "pending"

    await db.commit()
    await db.refresh(row)

    setup_needed = repo_changed or branch_settings_changed
    if row.repo_url and setup_needed:
        message = await setup_project_branches(
            workspace,
            row,
            github_token=await get_github_token(db, row.id),
            force_reclone=repo_changed,
        )
        await db.commit()
        workspace.append_log(row.id, "pipeline.log", f"[setup] {message}")
        await maybe_request_github_token(db, row.id, message)
    elif repo_changed and not row.repo_url:
        workspace.append_log(row.id, "pipeline.log", "[setup] GitHub repository unlinked")

    origin = await get_preview_origin(db, request)
    meta = workspace.load_metadata(project_id)
    preview_url = preview_from_metadata(meta, origin=origin, project_id=project_id)["preview_url"]
    return _project_from_row(row, preview_url=preview_url)


@router.delete("/{project_id}")
async def remove_project(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await delete_project_record(db, project_id, workspace=workspace)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "deleted", "project_id": str(project_id)}


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
