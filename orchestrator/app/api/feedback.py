from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.models import (
    InputRequest,
    InputRequestRespond,
    ProgressDigest,
    ProjectNote,
    ProjectNoteCreate,
)
from app.pipeline.executor import pipeline_executor
from app.services.input_requests import list_input_requests, respond_to_input
from app.services.notes import add_note, list_notes
from app.services.progress import get_progress_digest

router = APIRouter(prefix="/projects", tags=["feedback"])


@router.get("/{project_id}/progress", response_model=ProgressDigest)
async def project_progress(project_id: UUID, db: AsyncSession = Depends(get_db)) -> ProgressDigest:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await get_progress_digest(
        db, project_id, row.state, pipeline_executor.is_running(project_id)
    )


@router.get("/{project_id}/notes", response_model=list[ProjectNote])
async def get_notes(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[ProjectNote]:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await list_notes(db, project_id)


@router.post("/{project_id}/notes", response_model=ProjectNote, status_code=201)
async def create_note(
    project_id: UUID, body: ProjectNoteCreate, db: AsyncSession = Depends(get_db)
) -> ProjectNote:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await add_note(db, project_id, body)


@router.get("/{project_id}/input-requests", response_model=list[InputRequest])
async def get_input_requests(
    project_id: UUID,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[InputRequest]:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await list_input_requests(db, project_id, status)


@router.post("/{project_id}/input-requests/{request_id}/respond", response_model=InputRequest)
async def respond_input_request(
    project_id: UUID,
    request_id: UUID,
    body: InputRequestRespond,
    db: AsyncSession = Depends(get_db),
) -> InputRequest:
    result = await respond_to_input(db, project_id, request_id, body.response)
    if not result:
        raise HTTPException(status_code=404, detail="Input request not found or already resolved")
    return result
