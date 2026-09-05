"""Self-propelling post-production improvement cycle stages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import AgentRole, NotificationType
from app.services.factory_settings import get_preview_origin
from app.services.notifications import create_notification
from app.services.preview import preview_from_metadata
from app.services.self_propelling import (
    get_self_propelling_settings,
    mark_cycle_completed,
    resolve_post_production_passes,
)

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_post_production_enrichment(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.pipeline.stages.enrichment import run_enrichment_passes

    max_passes = resolve_post_production_passes(project.id, ex.workspace)
    ok = await run_enrichment_passes(
        ex,
        session,
        project,
        context,
        max_passes=max_passes,
        completion_key="post_production_enrichment_complete",
        log_prefix="post-production",
        completed_slugs_key="post_production_completed",
        passes_completed_key="post_production_passes_completed",
        token_budget=True,
        skip_unchanged_audit=True,
    )
    if ok:
        context["post_production_enrichment_complete"] = True
    return ok


async def stage_post_production_testing(ex: "PipelineExecutor", session, project, context) -> bool:
    int_task = await ex.create_task(
        session,
        project.id,
        "Post-production integration tests",
        "Validate API workflows after improvements",
        AgentRole.TESTER,
    )
    int_ok, int_output = await ex.test_runner.run_integration(project.id, context)
    await ex.complete_task(session, int_task, int_ok, int_output)
    if not int_ok:
        context["last_failure"] = int_output
        return False

    mobile_task = await ex.create_task(
        session,
        project.id,
        "Post-production mobile check",
        "Verify mobile-friendly layout",
        AgentRole.TESTER,
    )
    mobile_ok, mobile_output = await ex.test_runner.run_mobile_check(project.id, context)
    await ex.complete_task(session, mobile_task, mobile_ok, mobile_output)
    if not mobile_ok:
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[post-production] Mobile check noted issues: {mobile_output[:200]}",
        )

    qa_task = await ex.create_task(
        session,
        project.id,
        "Post-production product QA",
        "Evaluate live preview quality",
        AgentRole.TESTER,
    )
    qa_ok, qa_output = await ex.test_runner.run_product_qa(project.id, context)
    await ex.complete_task(session, qa_task, qa_ok, qa_output)

    context["post_production_tests_complete"] = True
    await ex._log_progress(
        session,
        project.id,
        "test",
        "Post-production tests complete",
        f"Integration {'passed' if int_ok else 'failed'}; mobile {'ok' if mobile_ok else 'issues noted'}",
    )
    return int_ok


async def stage_post_production_redeploy(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.pipeline.stages.build_deploy import build_project_image, verify_deployment

    production_state = project.state
    build_ok = await build_project_image(ex, session, project, context)
    if not build_ok:
        return False

    tag = context.get("image_tag", project.image_tag)
    deploy_ok = await ex._deploy_live_preview(
        session,
        project,
        context,
        preview_type="docker",
        image_tag=tag,
    )
    if not deploy_ok:
        return False

    smoke_task = await ex.create_task(
        session,
        project.id,
        "Post-production smoke test",
        "Health check after redeploy",
        AgentRole.TESTER,
    )
    smoke_ok, smoke_output = await ex.test_runner.run_smoke(project.id, context)
    await ex.complete_task(session, smoke_task, smoke_ok, smoke_output)
    if not smoke_ok:
        context["last_failure"] = smoke_output
        return False

    verified = await verify_deployment(ex, session, project, context, image_tag=tag or "dev")
    if not verified:
        return False

    project.state = production_state
    await session.commit()

    meta = ex.workspace.load_metadata(project.id)
    meta["production_url"] = True
    meta.pop("post_production_pending", None)
    meta.pop("pipeline_substage", None)
    ex.workspace.save_metadata(project.id, meta)
    mark_cycle_completed(project.id, ex.workspace)
    context["post_production_redeploy_complete"] = True

    origin = context.get("preview_origin") or await get_preview_origin(session)
    preview = preview_from_metadata(meta, origin=origin, project_id=project.id)
    prod_url = preview.get("preview_url") or ""

    await ex._log_progress(
        session,
        project.id,
        "post_production",
        "Self-propelling cycle complete",
        f"Production preview updated{f' at {prod_url}' if prod_url else ''}",
    )
    await create_notification(
        session,
        project.id,
        NotificationType.PROJECT_FINISHED,
        "Self-propelling cycle complete",
        f"{project.name} was improved and redeployed."
        + (
            " Next rapid cycle queued."
            if get_self_propelling_settings(project.id, ex.workspace).get("rapid_iterations")
            else " Next cycle scheduled automatically."
        ),
        action="overview",
    )
    return True
