from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import DeploymentRow, ProjectRow
from app.models import Deployment, ProjectState
from app.services.discovery import get_discovery
from app.pipeline.executor import pipeline_executor
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
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "state": row.state,
        "branch": row.branch,
        "image_tag": row.image_tag,
        "staging_url": meta.get("staging_url"),
        "production_url": meta.get("production_url"),
        "artifacts": workspace.list_artifacts(project_id),
        "pipeline_running": pipeline_executor.is_running(project_id),
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
    }
    if row.state == ProjectState.INTAKE_PENDING.value:
        raise HTTPException(
            status_code=400,
            detail="Complete the intake form before starting the build pipeline",
        )
    if row.state in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value):
        raise HTTPException(
            status_code=400,
            detail="Discovery is still in progress — wait for the intake form",
        )
    if row.state not in allowed_states and row.state != ProjectState.PRODUCTION.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot run pipeline from state {row.state}",
        )

    await pipeline_queue.enqueue_pipeline(project_id)
    return {"status": "queued", "project_id": str(project_id)}


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
