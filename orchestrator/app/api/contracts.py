"""Contract, requirements/evidence, and factory metrics API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contract import ProjectContract
from app.database import get_db
from app.db_models import PipelineRunRow, ProjectRow
from app.models import ProjectState
from app.services.contracts import (
    contract_history,
    get_latest_contract,
    save_contract,
    write_contract_artifacts,
)
from app.services.evidence import (
    list_requirements_with_evidence,
    project_health,
    set_requirement_status,
    sync_requirements_from_contract,
)
from app.workspace.manager import WorkspaceManager

router = APIRouter(tags=["contracts"])
workspace = WorkspaceManager()


async def _get_project(db: AsyncSession, project_id: UUID) -> ProjectRow:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.get("/projects/{project_id}/contract")
async def get_contract(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    await _get_project(db, project_id)
    contract = await get_latest_contract(db, project_id)
    history = await contract_history(db, project_id)
    return {
        "contract": contract.model_dump() if contract else None,
        "version": contract.version if contract else None,
        "source": contract.source if contract else None,
        "history": history,
    }


@router.put("/projects/{project_id}/contract")
async def update_contract(
    project_id: UUID, body: dict, db: AsyncSession = Depends(get_db)
) -> dict:
    """Human contract edit: new version, synced requirements, feedback at REVIEW."""
    project = await _get_project(db, project_id)
    try:
        contract = ProjectContract.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not contract.requirements:
        raise HTTPException(status_code=422, detail="Contract needs at least one requirement")

    saved = await save_contract(db, project_id, contract, source="human")
    write_contract_artifacts(workspace, project_id, saved)
    await sync_requirements_from_contract(db, project_id, saved)

    feedback_scheduled = False
    if project.state == ProjectState.REVIEW.value:
        from app.services.feedback_pipeline import maybe_schedule_feedback_pipeline

        feedback_scheduled = await maybe_schedule_feedback_pipeline(db, project_id)

    return {
        "contract": saved.model_dump(),
        "version": saved.version,
        "source": saved.source,
        "feedback_scheduled": feedback_scheduled,
    }


@router.get("/projects/{project_id}/requirements")
async def get_requirements(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    await _get_project(db, project_id)
    requirements = await list_requirements_with_evidence(db, project_id)
    health = await project_health(db, project_id)
    return {"requirements": requirements, "health": health}


@router.post("/projects/{project_id}/requirements/{req_id}/waive")
async def waive_requirement(
    project_id: UUID, req_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    await _get_project(db, project_id)
    if not await set_requirement_status(db, project_id, req_id, "waived"):
        raise HTTPException(status_code=404, detail="Requirement not found")
    return {"req_id": req_id.upper(), "status": "waived"}


@router.post("/projects/{project_id}/requirements/{req_id}/unwaive")
async def unwaive_requirement(
    project_id: UUID, req_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    await _get_project(db, project_id)
    if not await set_requirement_status(db, project_id, req_id, "pending"):
        raise HTTPException(status_code=404, detail="Requirement not found")
    return {"req_id": req_id.upper(), "status": "pending"}


@router.get("/metrics/factory")
async def factory_metrics(db: AsyncSession = Depends(get_db)) -> dict:
    """Outcome metrics across pipeline runs — not token counts."""
    result = await db.execute(
        select(PipelineRunRow).order_by(PipelineRunRow.started_at.desc()).limit(200)
    )
    runs = list(result.scalars())
    finished = [r for r in runs if r.finished_at is not None]
    completed = [r for r in finished if r.outcome == "completed"]

    def _avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    durations = [
        (r.finished_at - r.started_at).total_seconds() for r in completed if r.finished_at
    ]
    total_projects = await db.scalar(select(func.count(ProjectRow.id))) or 0

    return {
        "total_projects": total_projects,
        "runs_recorded": len(runs),
        "runs_completed": len(completed),
        "runs_blocked": sum(1 for r in finished if r.outcome == "blocked"),
        "runs_stopped": sum(1 for r in finished if r.outcome == "stopped"),
        "success_rate": round(len(completed) / len(finished), 3) if finished else None,
        "avg_fix_attempts_per_run": _avg([float(r.fix_attempts) for r in finished]),
        "avg_infra_retries_per_run": _avg([float(r.infra_retries) for r in finished]),
        "avg_human_interventions_per_completed_run": _avg(
            [float(r.human_interventions) for r in completed]
        ),
        "avg_auto_resolved_inputs_per_run": _avg(
            [float(r.auto_resolved_inputs) for r in finished]
        ),
        "mean_seconds_to_successful_run": _avg(durations),
        "recent_runs": [
            {
                "project_id": str(r.project_id),
                "mode": r.mode,
                "outcome": r.outcome,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "fix_attempts": r.fix_attempts,
                "human_interventions": r.human_interventions,
                "gates_failed": r.gates_failed,
            }
            for r in runs[:20]
        ],
    }
