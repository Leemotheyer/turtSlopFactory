from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.db_models import DeploymentRow, ProjectRow
from app.models import Deployment, ProjectState
from app.services.git_branching import merge_work_branch_to_base, resolve_branch_plan
from app.services.secrets import get_github_token, maybe_request_github_token
from app.services.discovery import get_discovery
from app.pipeline.executor import pipeline_executor
from app.services.factory_settings import get_preview_origin
from app.services.pipeline_launcher import schedule_pipeline, stop_pipeline
from app.services.preview import preview_from_metadata
from app.services.agent_activity import get_agent_activity
from app.services.self_propelling import (
    get_self_propelling_settings,
    maybe_schedule_post_production,
    save_self_propelling_settings,
)
from app.workspace.manager import WorkspaceManager

router = APIRouter(prefix="/projects", tags=["pipeline"])
workspace = WorkspaceManager()


@router.get("/{project_id}/detail")
async def get_project_detail(project_id: UUID, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    meta = workspace.load_metadata(project_id)
    discovery = await get_discovery(db, project_id)
    origin = await get_preview_origin(db, request)
    preview = preview_from_metadata(meta, origin=origin, project_id=project_id)
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "repo_url": row.repo_url,
        "state": row.state,
        "branch": row.branch,
        "base_branch": row.base_branch or "main",
        "work_branch": row.work_branch,
        "isolate_branch": bool(row.isolate_branch),
        "merge_status": row.merge_status,
        "image_tag": row.image_tag,
        "staging_url": preview["staging_url"],
        "production_url": preview["preview_url"] if meta.get("production_url") else None,
        "preview_url": preview["preview_url"],
        "preview_port": preview["preview_port"],
        "preview_type": preview["preview_type"],
        "preview_status": preview["preview_status"],
        "artifacts": workspace.list_artifacts(project_id),
        "pipeline_running": pipeline_executor.is_running(project_id),
        "pipeline_paused": bool(meta.get("pipeline_paused")),
        "pipeline_paused_at": meta.get("pipeline_paused_at"),
        "failed_gate": meta.get("failed_gate"),
        "failed_substage": meta.get("failed_substage"),
        "max_enrichment_passes": row.max_enrichment_passes,
        "factory_default_enrichment_passes": settings.max_enrichment_passes,
        "effective_enrichment_passes": (
            row.max_enrichment_passes
            if row.max_enrichment_passes is not None
            else settings.max_enrichment_passes
        ),
        "pipeline_substage": meta.get("pipeline_substage"),
        "enrichment_progress": meta.get("enrichment"),
        "self_propelling": get_self_propelling_settings(project_id, workspace),
        "discovery_status": discovery.status.value if discovery else None,
        "intake_ready": discovery is not None and discovery.status.value == "awaiting_user",
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.post("/{project_id}/run")
async def run_pipeline(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    if pipeline_executor.is_running(project_id):
        return {"status": "already_running", "project_id": str(project_id)}

    allowed_states = {
        ProjectState.PLANNING.value,
        ProjectState.IMPLEMENTING.value,
        ProjectState.UNIT_TESTING.value,
        ProjectState.INTEGRATION_TESTING.value,
        ProjectState.DOCKER_BUILD.value,
        ProjectState.STAGING_DEPLOY.value,
        ProjectState.SMOKE_TESTING.value,
        ProjectState.REVIEW.value,
        ProjectState.DIAGNOSING.value,
        ProjectState.FIXING.value,
        ProjectState.AUTONOMOUSLY_BLOCKED.value,
    }
    if row.state == ProjectState.INTAKE_PENDING.value:
        raise HTTPException(
            status_code=400,
            detail="Complete the intake form before starting the build pipeline",
        )
    if row.state == ProjectState.PRODUCTION.value:
        settings_data = get_self_propelling_settings(project_id, workspace)
        if not settings_data.get("enabled"):
            raise HTTPException(
                status_code=400,
                detail="Project is in production — enable self-propelling development to run improvement cycles",
            )
        meta = workspace.load_metadata(project_id)
        meta["post_production_pending"] = True
        workspace.save_metadata(project_id, meta)
    elif row.state in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value):
        raise HTTPException(
            status_code=400,
            detail="Discovery is still in progress — wait for the intake form",
        )
    elif row.state not in allowed_states:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot run pipeline from state {row.state}",
        )

    started = schedule_pipeline(project_id, force=True)
    if not started:
        return {"status": "already_running", "project_id": str(project_id)}
    mode = "feedback" if row.state == ProjectState.REVIEW.value else "pipeline"
    if row.state == ProjectState.PRODUCTION.value:
        mode = "post_production"
    return {"status": "started", "project_id": str(project_id), "mode": mode}


@router.patch("/{project_id}/self-propelling")
async def update_self_propelling(
    project_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    enabled = body.get("enabled")
    post_production_passes = body.get("post_production_passes")
    interval_hours = body.get("interval_hours")
    token_budget_per_cycle = body.get("token_budget_per_cycle")

    if post_production_passes is not None:
        value = int(post_production_passes)
        if value < 0 or value > 10:
            raise HTTPException(status_code=400, detail="post_production_passes must be between 0 and 10")
        post_production_passes = value

    if interval_hours is not None:
        value = int(interval_hours)
        if value < 1 or value > 168:
            raise HTTPException(status_code=400, detail="interval_hours must be between 1 and 168")
        interval_hours = value

    if token_budget_per_cycle is not None:
        value = int(token_budget_per_cycle)
        if value < 0:
            raise HTTPException(status_code=400, detail="token_budget_per_cycle must be >= 0")
        token_budget_per_cycle = value if value > 0 else None

    sp_settings = save_self_propelling_settings(
        project_id,
        enabled=enabled if enabled is not None else None,
        post_production_passes=post_production_passes,
        interval_hours=interval_hours,
        token_budget_per_cycle=token_budget_per_cycle,
        workspace=workspace,
    )

    if enabled and row.state == ProjectState.PRODUCTION.value:
        await maybe_schedule_post_production(db, project_id, force=True)

    return sp_settings


@router.post("/{project_id}/stop")
async def stop_project_pipeline(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    await stop_pipeline(project_id)
    return {
        "status": "stopped",
        "project_id": str(project_id),
        "pipeline_paused": True,
    }


@router.get("/{project_id}/agent-activity")
async def get_project_agent_activity(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    return await get_agent_activity(
        db,
        project_id,
        pipeline_running=pipeline_executor.is_running(project_id),
        stop_requested=pipeline_executor.is_stop_requested(project_id),
        current_state=row.state,
    )


@router.post("/{project_id}/promote")
async def promote_to_production(
    project_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    if row.state != "REVIEW":
        raise HTTPException(status_code=400, detail=f"Project must be in REVIEW state, got {row.state}")

    success = await pipeline_executor.promote_to_production(project_id)
    if not success:
        raise HTTPException(status_code=500, detail="Promotion failed")

    await db.refresh(row)
    meta = workspace.load_metadata(project_id)
    origin = await get_preview_origin(db, request)
    preview = preview_from_metadata(meta, origin=origin, project_id=project_id)
    return {
        "status": "promoted",
        "state": row.state,
        "production_url": preview["preview_url"] if meta.get("production_url") else None,
    }


@router.post("/{project_id}/merge-to-main")
async def merge_to_main(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    if not row.repo_url or not row.isolate_branch:
        raise HTTPException(status_code=400, detail="Project does not use isolated factory branches")

    plan = resolve_branch_plan(row)
    if not plan.work_branch:
        raise HTTPException(status_code=400, detail="No factory work branch configured")

    success, message = await merge_work_branch_to_base(
        workspace,
        project_id,
        row.repo_url,
        plan.base_branch,
        plan.work_branch,
        github_token=await get_github_token(db, project_id),
    )
    workspace.append_log(project_id, "pipeline.log", f"[merge] {message}")

    if not success:
        raise HTTPException(status_code=500, detail=message)

    row.merge_status = "merged"
    await db.commit()
    return {
        "status": "merged",
        "message": message,
        "base_branch": plan.base_branch,
        "work_branch": plan.work_branch,
    }


@router.get("/{project_id}/artifacts/{name}")
async def get_artifact(project_id: UUID, name: str) -> dict:
    content = workspace.read_artifact(project_id, name)
    if content is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"name": name, "content": content}


@router.get("/{project_id}/logs/{name}")
async def get_log(project_id: UUID, name: str) -> dict:
    path = workspace.logs_dir(project_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return {"name": name, "content": path.read_text()}


@router.get("/{project_id}/deployments", response_model=list[Deployment])
async def list_deployments(project_id: UUID, db: AsyncSession = Depends(get_db)) -> list[Deployment]:
    result = await db.execute(
        select(DeploymentRow)
        .where(DeploymentRow.project_id == project_id)
        .order_by(DeploymentRow.created_at.desc())
    )
    return [
        Deployment(
            id=r.id,
            project_id=r.project_id,
            environment=r.environment,
            image_tag=r.image_tag,
            url=r.url,
            port=r.port,
            container_id=r.container_id,
            status=r.status,
            created_at=r.created_at,
        )
        for r in result.scalars()
    ]
