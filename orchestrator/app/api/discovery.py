from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.models import DiscoverySession, IntakeSubmit, ProjectState
from app.services.discovery import get_discovery, run_discovery, submit_intake
from app.services.pipeline_launcher import schedule_pipeline
from app.worker import pipeline_queue

router = APIRouter(prefix="/projects", tags=["discovery"])


@router.get("/{project_id}/discovery", response_model=DiscoverySession | None)
async def fetch_discovery(project_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await get_discovery(db, project_id)


@router.post("/{project_id}/discovery", response_model=DiscoverySession)
async def start_discovery(project_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    existing = await get_discovery(db, project_id)
    if existing and existing.status.value != "generating":
        return existing

    if row.state in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value):
        try:
            return await run_discovery(db, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    await pipeline_queue.enqueue_discovery(project_id)
    if existing:
        return existing
    from app.models import DiscoveryStatus

    return DiscoverySession(project_id=project_id, status=DiscoveryStatus.GENERATING)


@router.post("/{project_id}/discovery/submit", response_model=DiscoverySession)
async def submit_discovery_intake(
    project_id: UUID, body: IntakeSubmit, db: AsyncSession = Depends(get_db)
):
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if row.state != ProjectState.INTAKE_PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Project must be awaiting intake, current state: {row.state}",
        )
    try:
        session = await submit_intake(db, project_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule_pipeline(project_id)
    return session
