"""Factory-owned live preview deployment (dev reload and docker/staging)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import DeploymentRow, ProjectRow
from app.models import EventType, NotificationType
from app.services.factory_settings import get_preview_origin
from app.services.notifications import create_notification
from app.services.preview import (
    build_preview_url,
    preview_path,
    preview_upstream,
    restore_preview_meta,
    snapshot_preview_meta,
    update_preview_metadata,
)
from app.services.preview_manager import (
    container_is_running,
    preview_container_name,
    preview_staging_container_name,
    promote_preview_container,
    start_dev_preview,
    start_docker_preview,
    stop_preview,
)
from app.services.preview_spec import PreviewLaunch, load_preview_spec
from app.services.secrets import get_secrets_for_runtime

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def deploy_live_preview(
    ex: "PipelineExecutor",
    session: AsyncSession,
    project: ProjectRow,
    context: dict,
    *,
    preview_type: str,
    image_tag: str | None = None,
    notify: bool = False,
) -> bool:
    """Start or replace the factory-owned preview container. Agents never launch this."""
    meta = ex.workspace.load_metadata(project.id)
    if preview_type == "dev":
        await ex._ensure_runnable_app(project, context)

    origin = context.get("preview_origin") or await get_preview_origin(session)
    preview_url = build_preview_url(project.id, origin=origin)
    runtime_env = await get_secrets_for_runtime(session, project.id)
    repo = ex.workspace.repo_dir(project.id)
    spec = load_preview_spec(repo)

    canonical = preview_container_name(project.id)
    preview_snapshot = snapshot_preview_meta(meta)
    keep_live = (
        meta.get("preview_status") == "running"
        and await container_is_running(canonical)
    )
    target_name = preview_staging_container_name(project.id) if keep_live else canonical

    if keep_live:
        await stop_preview(project.id, container_name=target_name)
    else:
        await stop_preview(
            project.id,
            container_name=meta.get("preview_container"),
            ephemeral_image=meta.get("preview_ephemeral_image"),
        )

    launch_kwargs = {
        "container_name": target_name,
        "stop_before_start": not keep_live,
    }

    launch = PreviewLaunch(
        success=False,
        message="Preview was not attempted",
        backend="simulated",
        failure_kind="infra",
    )

    if preview_type == "dev":
        if ex.runner.docker_available():
            log_path = ex.workspace.logs_dir(project.id) / "preview-dev.log"
            launch = await start_dev_preview(
                project.id,
                repo,
                log_path,
                env_vars=runtime_env,
                **launch_kwargs,
            )
        else:
            launch = PreviewLaunch(
                success=False,
                message="Docker is required for live preview",
                backend="simulated",
                failure_kind="infra",
            )
    elif ex.runner.docker_available():
        tag = image_tag or project.image_tag or context.get("image_tag", "none")
        if tag == "none":
            launch = PreviewLaunch(
                success=False,
                message="No image tag",
                failure_kind="infra",
            )
        else:
            log_path = ex.workspace.logs_dir(project.id) / "preview-staging.log"
            launch = await start_docker_preview(
                project.id,
                tag,
                env_vars=runtime_env,
                repo_path=repo,
                log_path=log_path,
                **launch_kwargs,
            )
    else:
        launch = PreviewLaunch(
            success=True,
            message=f"No Docker — simulated preview at {preview_url}",
            backend="simulated",
        )

    success = launch.success
    output = launch.message
    container_id = launch.container_id
    container_name = launch.container_name or (
        canonical if launch.backend == "docker" and success else None
    )

    if success and keep_live:
        promoted = await promote_preview_container(project.id, target_name)
        if not promoted:
            await stop_preview(project.id, container_name=target_name)
            success = False
            output = "Could not promote staged preview container"
            launch = PreviewLaunch(
                success=False,
                message=output,
                backend=launch.backend,
                failure_kind="infra",
            )
        else:
            container_name = canonical

    if not success and keep_live:
        restore_preview_meta(meta, preview_snapshot)
        ex.workspace.save_metadata(project.id, meta)
        context["preview_status"] = meta.get("preview_status")
        context["preview_upstream"] = preview_upstream(project.id, meta)
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[preview] kept existing live preview running after failed update: {output[:300]}",
        )
        return False

    backend = launch.backend
    context["preview_backend"] = backend if success else None
    context["preview_container"] = container_name
    context["preview_url"] = preview_url
    context["preview_path"] = preview_path(project.id)
    context["preview_health_path"] = spec.path
    context["preview_app_port"] = spec.port

    status = "running" if success else "failed"
    if not success:
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[preview] failed ({launch.failure_kind or 'unknown'}): {output[:1500]}",
        )
        ex.workspace.write_log(project.id, "preview-failure.log", output)
    else:
        ex.workspace.append_log(project.id, "pipeline.log", f"[preview] {output}")

    update_preview_metadata(
        meta,
        project_id=project.id,
        port=None,
        preview_type=preview_type,
        status=status,
        backend=backend,
        origin=origin,
        host=None,
        container_id=container_id,
        container_name=container_name,
        ephemeral_image=launch.ephemeral_image,
        health_path=spec.path,
        app_port=spec.port,
        failure_kind=launch.failure_kind,
    )
    ex.workspace.save_metadata(project.id, meta)
    context["preview_status"] = status
    context["preview_upstream"] = preview_upstream(project.id, meta)

    environment = "preview" if preview_type == "dev" else "staging"
    previous_tag = await _latest_deployment_tag(session, project.id, environment)
    dep = DeploymentRow(
        project_id=project.id,
        environment=environment,
        image_tag=image_tag or project.image_tag or "dev",
        url=preview_url,
        port=None,
        container_id=container_id,
        status=status,
        previous_tag=previous_tag,
    )
    session.add(dep)
    await session.commit()
    context["last_deployment_id"] = str(dep.id)

    await ex.emit(
        session,
        EventType.DEPLOYMENT_FINISHED,
        project.id,
        payload={
            "environment": preview_type,
            "url": preview_url,
            "success": success,
            "preview_type": preview_type,
            "failure_kind": launch.failure_kind,
        },
    )

    if success:
        await ex._log_progress(
            session,
            project.id,
            "deploy",
            "Live preview updated",
            f"Open {preview_url} ({preview_type})",
            output[:200] if output else None,
        )
    elif launch.failure_kind == "app":
        context["last_failure"] = (
            "Factory live preview failed to start the app. "
            "Do NOT run docker, docker compose, or uvicorn — the factory owns the preview container. "
            "Fix the application so it listens on 0.0.0.0:8080 and GET /health returns HTTP 200.\n\n"
            f"{output[:3500]}"
        )
        ex._persist_last_failure(project.id, context)

    if notify and success:
        await create_notification(
            session,
            project.id,
            NotificationType.PREVIEW_READY,
            "Live preview ready",
            f"{project.name} is running at {preview_url}. Check it while agents iterate.",
            action="preview",
        )

    return success


async def _latest_deployment_tag(
    session: AsyncSession, project_id, environment: str
) -> str | None:
    from sqlalchemy import select

    result = await session.execute(
        select(DeploymentRow.image_tag)
        .where(
            DeploymentRow.project_id == project_id,
            DeploymentRow.environment == environment,
            DeploymentRow.status == "running",
        )
        .order_by(DeploymentRow.created_at.desc())
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None
