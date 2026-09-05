"""Docker build, staging deploy, and post-deploy verification / rollback."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.db_models import DeploymentRow
from app.models import EventType, NotificationType
from app.services.build_manifest import write_build_manifest
from app.services.evidence import record_evidence
from app.services.notifications import create_notification

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def build_project_image(ex: "PipelineExecutor", session, project, context) -> bool:
    build_id = f"build-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    tag = f"factory/{project.name.lower().replace(' ', '-')}:{build_id}"
    context["image_tag"] = tag
    context["build_id"] = build_id

    if ex.runner.docker_available():
        success, output = await ex.runner.docker_build(project.id, tag)
    else:
        success = True
        output = "Docker not available — simulated build success"
        ex.workspace.append_log(project.id, "pipeline.log", f"[build] simulated {tag}")

    await ex.emit(
        session,
        EventType.AGENT_COMMAND_FINISHED,
        project.id,
        payload={"command": "docker build", "success": success, "tag": tag},
    )

    await record_evidence(
        session,
        project.id,
        kind="build",
        reference=tag,
        passed=success,
        payload={"build_id": build_id, "output_tail": (output or "")[-1000:]},
    )

    if success:
        project.image_tag = tag
        await session.commit()
        manifest = await write_build_manifest(
            ex.workspace, session, project, build_id=build_id, image_tag=tag
        )
        context["build_manifest"] = manifest
    else:
        context["last_failure"] = output
    return success


async def stage_docker_build(ex: "PipelineExecutor", session, project, context) -> bool:
    success = await build_project_image(ex, session, project, context)
    tag = context.get("image_tag", project.image_tag or "none")

    if success:
        await ex._log_progress(
            session,
            project.id,
            "deploy",
            "Docker image built",
            f"Tagged as {tag}",
        )
    return success


async def stage_staging_deploy(ex: "PipelineExecutor", session, project, context) -> bool:
    tag = context.get("image_tag", project.image_tag or "none")

    await ex.emit(
        session,
        EventType.DEPLOYMENT_STARTED,
        project.id,
        payload={"environment": "staging", "image_tag": tag},
    )

    success = await ex._deploy_live_preview(
        session,
        project,
        context,
        preview_type="docker",
        image_tag=tag,
    )

    if not success:
        if not context.get("last_failure"):
            context["last_failure"] = "Staging deploy failed"
        return False

    verified = await verify_deployment(ex, session, project, context, image_tag=tag)
    return verified


async def verify_deployment(
    ex: "PipelineExecutor", session, project, context, *, image_tag: str
) -> bool:
    """Observe the deployment for a short window; roll back to the previous tag on regression.

    Simulated (no-docker) deploys skip verification — there is nothing to probe.
    """
    if context.get("preview_backend") != "docker":
        await _set_deployment_verification(session, context, "skipped")
        return True

    upstream = context.get("preview_upstream")
    health_path = context.get("preview_health_path") or "/health"
    if not str(health_path).startswith("/"):
        health_path = f"/{health_path}"
    if not upstream:
        await _set_deployment_verification(session, context, "skipped")
        return True

    polls = max(1, settings.deploy_observation_polls)
    interval = max(0.0, settings.deploy_observation_seconds / polls)
    url = f"{upstream.rstrip('/')}{health_path}"
    failures = 0
    checks: list[dict] = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(polls):
            ok = False
            status_code = None
            try:
                response = await client.get(url)
                status_code = response.status_code
                ok = 200 <= response.status_code < 300
            except httpx.HTTPError:
                ok = False
            checks.append({"attempt": attempt + 1, "status": status_code, "ok": ok})
            if not ok:
                failures += 1
            if attempt < polls - 1 and interval:
                await asyncio.sleep(interval)

    healthy = failures == 0
    ex.workspace.write_artifact(
        project.id,
        "deploy-verification.json",
        json.dumps(
            {
                "image_tag": image_tag,
                "url": url,
                "healthy": healthy,
                "checks": checks,
                "observed_seconds": settings.deploy_observation_seconds,
            },
            indent=2,
        ),
    )

    await record_evidence(
        session,
        project.id,
        kind="probe",
        reference=f"deploy-verification:{image_tag}",
        passed=healthy,
        payload={"checks": checks, "url": url},
    )

    if healthy:
        await _set_deployment_verification(session, context, "verified")
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[deploy] Verified {image_tag} over {settings.deploy_observation_seconds}s window",
        )
        from app.services.preview_manager import prune_stale_project_build_images

        if image_tag and image_tag not in ("dev", "none"):
            keep_tag = image_tag.split(":", 1)[-1] if ":" in image_tag else image_tag
            removed = await prune_stale_project_build_images(
                project.name,
                keep_tags={keep_tag},
            )
            if removed:
                ex.workspace.append_log(
                    project.id,
                    "pipeline.log",
                    f"[deploy] Removed {len(removed)} old preview image(s) after verification",
                )
        return True

    # Regression: roll back to the previous running tag when one exists.
    previous_tag = await _previous_staging_tag(session, project.id, exclude_tag=image_tag)
    await _set_deployment_verification(session, context, "rolled_back")
    ex.workspace.append_log(
        project.id,
        "pipeline.log",
        f"[deploy] Health regression on {image_tag} — "
        + (f"rolling back to {previous_tag}" if previous_tag else "no previous tag to roll back to"),
    )

    if previous_tag:
        rolled = await ex._deploy_live_preview(
            session,
            project,
            context,
            preview_type="docker",
            image_tag=previous_tag,
        )
        from app.services.preview_manager import remove_docker_image

        if image_tag and image_tag not in ("dev", "none"):
            await remove_docker_image(image_tag)
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[deploy] Removed failed image {image_tag}",
            )
        await create_notification(
            session,
            project.id,
            NotificationType.PIPELINE_BLOCKED,
            "Deployment rolled back",
            (
                f"{project.name}: {image_tag} failed post-deploy health checks; "
                f"{'restored ' + previous_tag if rolled else 'rollback to ' + previous_tag + ' also failed'}."
            ),
            action="overview",
        )

    context["last_failure"] = (
        f"Deployment verification failed for {image_tag}: {failures}/{polls} health checks failed at {url}."
        + (f" Rolled back to {previous_tag}." if previous_tag else "")
    )
    return False


async def _previous_staging_tag(session, project_id, *, exclude_tag: str) -> str | None:
    from sqlalchemy import select

    result = await session.execute(
        select(DeploymentRow.image_tag)
        .where(
            DeploymentRow.project_id == project_id,
            DeploymentRow.environment == "staging",
            DeploymentRow.status == "running",
            DeploymentRow.image_tag != exclude_tag,
            DeploymentRow.image_tag != "dev",
        )
        .order_by(DeploymentRow.created_at.desc())
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def _set_deployment_verification(session, context, status: str) -> None:
    dep_id = context.get("last_deployment_id")
    if not dep_id:
        return
    from uuid import UUID

    dep = await session.get(DeploymentRow, UUID(dep_id))
    if dep:
        dep.verification_status = status
        await session.commit()
