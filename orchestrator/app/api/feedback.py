from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.models import (
    InputRequest,
    InputRequestRespond,
    NoteType,
    ProgressDigest,
    ProjectNote,
    ProjectNoteCreate,
    ProjectNoteUpdate,
)
from app.pipeline.executor import pipeline_executor
from app.services.feedback_pipeline import (
    maybe_schedule_feedback_pipeline,
    should_schedule_feedback_on_input_response,
    wants_merge_to_main,
)
from app.services.git_branching import merge_work_branch_to_base, resolve_branch_plan
from app.services.input_requests import list_input_requests, respond_to_input
from app.services.notes import add_note, delete_note, get_note, list_notes, update_note
from app.services.progress import get_progress_digest
from app.services.secrets import get_github_token
from app.workspace.manager import WorkspaceManager

router = APIRouter(prefix="/projects", tags=["feedback"])
workspace = WorkspaceManager()


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
    note = await add_note(db, project_id, body)
    if body.note_type in (NoteType.INSTRUCTION, NoteType.FEATURE, NoteType.SCOPE_OUT):
        await maybe_schedule_feedback_pipeline(db, project_id)
    return note


@router.patch("/{project_id}/notes/{note_id}", response_model=ProjectNote)
async def patch_note(
    project_id: UUID,
    note_id: UUID,
    body: ProjectNoteUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectNote:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.content is None and body.note_type is None:
        raise HTTPException(status_code=400, detail="At least one field must be provided")

    note = await update_note(db, project_id, note_id, body)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if note.note_type in (NoteType.INSTRUCTION, NoteType.FEATURE, NoteType.SCOPE_OUT):
        await maybe_schedule_feedback_pipeline(db, project_id)
    return note


@router.delete("/{project_id}/notes/{note_id}")
async def remove_note(
    project_id: UUID,
    note_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    target = await get_note(db, project_id, note_id)
    if not target:
        raise HTTPException(status_code=404, detail="Note not found")

    deleted = await delete_note(db, project_id, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")

    if target.note_type in (NoteType.INSTRUCTION, NoteType.FEATURE, NoteType.SCOPE_OUT):
        await maybe_schedule_feedback_pipeline(db, project_id)
    return {"status": "deleted", "note_id": str(note_id)}


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

    if wants_merge_to_main(body.response, result.question):
        project = await db.get(ProjectRow, project_id)
        if project and project.repo_url and project.isolate_branch:
            plan = resolve_branch_plan(project)
            if plan.work_branch and project.merge_status != "merged":
                success, message = await merge_work_branch_to_base(
                    workspace,
                    project_id,
                    project.repo_url,
                    plan.base_branch,
                    plan.work_branch,
                    github_token=await get_github_token(db, project_id),
                )
                workspace.append_log(project_id, "pipeline.log", f"[merge] {message}")
                if success:
                    project.merge_status = "merged"
                    await db.commit()
                else:
                    raise HTTPException(status_code=500, detail=message)
    else:
        if should_schedule_feedback_on_input_response(
            body.response, result.question, role=result.role
        ):
            await maybe_schedule_feedback_pipeline(db, project_id)

    return result
