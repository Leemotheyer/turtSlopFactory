from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import DeploymentRow, ProjectRow
from app.models import Deployment, ProjectState
from app.services.git_branching import merge_work_branch_to_base, resolve_branch_plan
from app.services.secrets import get_github_token, maybe_request_github_token
from app.services.discovery import get_discovery
from app.pipeline.executor import pipeline_executor
from app.services.factory_settings import get_preview_host
from app.services.pipeline_launcher import schedule_pipeline
from app.services.preview import preview_from_metadata
from app.services.self_propelled import (
    get_self_propelled_meta,
    is_self_propelled_enabled,
    set_self_propelled_enabled,
)
from app.worker import pipeline_queue
from app.workspace.manager import WorkspaceManager

router = APIRouter(prefix="/projects", tags=["pipeline"])
workspace = WorkspaceManager()


@router.get("/{project_id}/detail")
async def get_project_detail(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    meta = workspace.load_metadata(project_id)
    discovery = await get_discovery(db, project_id)
    host = await get_preview_host(db)
    preview = preview_from_metadata(meta, host=host, project_id=project_id)
    sp = get_self_propelled_meta(meta)
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
        "production_url": meta.get("production_url"),
        "preview_url": preview["preview_url"],
        "preview_port": preview["preview_port"],
        "preview_type": preview["preview_type"],
        "preview_status": preview["preview_status"],
        "artifacts": workspace.list_artifacts(project_id),
        "pipeline_running": pipeline_executor.is_running(project_id),
        "failed_gate": meta.get("failed_gate"),
        "failed_substage": meta.get("failed_substage"),
        "discovery_status": discovery.status.value if discovery else None,
        "intake_ready": discovery is not None and discovery.status.value == "awaiting_user",
        "self_propelled_enabled": is_self_propelled_enabled(meta),
        "self_propelled_iteration": int(sp.get("iteration", 0)),
        "self_propelled_max_iterations": int(sp.get("max_iterations", 20)),
        "self_propelled_paused_reason": sp.get("paused_reason"),
        "self_propelled_last_improvements": sp.get("last_improvements") or [],
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
        raise HTTPException(
            status_code=400,
            detail="Project is already in production — nothing to run",
        )
    if row.state in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value):
        raise HTTPException(
            status_code=400,
            detail="Discovery is still in progress — wait for the intake form",
        )
    if row.state not in allowed_states:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot run pipeline from state {row.state}",
        )

    started = schedule_pipeline(project_id)
    if not started:
        return {"status": "already_running", "project_id": str(project_id)}
    return {"status": "started", "project_id": str(project_id)}


@router.post("/{project_id}/promote")
async def promote_to_production(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
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
    return {
        "status": "promoted",
        "state": row.state,
        "production_url": meta.get("production_url"),
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


@router.patch("/{project_id}/self-propelled")
async def update_self_propelled(
    project_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    enabled = body.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="Missing 'enabled' field")

    sp = set_self_propelled_enabled(workspace, project_id, bool(enabled))
    return {
        "project_id": str(project_id),
        "self_propelled_enabled": sp.get("enabled", True),
        "self_propelled_iteration": int(sp.get("iteration", 0)),
        "self_propelled_max_iterations": int(sp.get("max_iterations", 20)),
        "self_propelled_paused_reason": sp.get("paused_reason"),
    }


@router.post("/{project_id}/self-propelled/resume")
async def resume_self_propelled(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Re-enable self-propelled development and queue another pipeline run from REVIEW."""
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    if row.state not in (ProjectState.REVIEW.value, ProjectState.PRODUCTION.value):
        raise HTTPException(
            status_code=400,
            detail=f"Can only resume self-propelled from REVIEW or PRODUCTION, got {row.state}",
        )

    set_self_propelled_enabled(workspace, project_id, True)
    if row.state == ProjectState.PRODUCTION.value:
        row.state = ProjectState.REVIEW.value
        await db.commit()

    if pipeline_executor.is_running(project_id):
        return {"status": "already_running", "project_id": str(project_id)}

    await pipeline_queue.enqueue_pipeline(project_id)
    return {"status": "queued", "project_id": str(project_id)}
