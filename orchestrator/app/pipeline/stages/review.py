"""Review gate (final reviewer agent) and production promotion."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db_models import DeploymentRow
from app.models import AgentRole, EventType, NotificationType, ProjectState
from app.services.git_branching import resolve_branch_plan
from app.services.input_requests import create_input_request
from app.services.notifications import create_notification
from app.services.preview import preview_from_metadata
from app.services.factory_settings import get_preview_origin
from app.state_machine import advance_project

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_review(ex: "PipelineExecutor", session, project, context) -> bool:
    await ex._refresh_context(session, project, context)
    context["tests_passed"] = True
    review_path = ex.workspace.artifacts_dir(project.id) / "review.json"
    if review_path.exists():
        review_path.unlink()
    task = await ex.create_task(
        session, project.id, "Code review", "Reviewer agent checklist", AgentRole.REVIEWER
    )
    run = await ex.runner.run(
        AgentRole.REVIEWER, project.id, task.id, str(ex.workspace.repo_dir(project.id)), context
    )
    await ex.complete_task(
        session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
    )
    if not run.success:
        context["last_failure"] = run.output
        return False

    meta = ex.workspace.load_metadata(project.id)
    meta["review_ever_approved"] = True
    ex.workspace.save_metadata(project.id, meta)
    context["review_ever_approved"] = True
    context["change_budget_enforced"] = True

    from app.services.evidence import record_evidence

    await record_evidence(
        session,
        project.id,
        kind="review",
        reference="review.json",
        passed=True,
        payload={"output": (run.output or "")[:2000]},
    )
    await ex._log_progress(
        session,
        project.id,
        "review",
        "Review approved",
        "All acceptance criteria met — ready for production promotion",
    )
    await ex.transition(session, project, advance_project(ProjectState.SMOKE_TESTING))
    await create_notification(
        session,
        project.id,
        NotificationType.REVIEW_READY,
        "Ready for production",
        f"{project.name} passed review. Promote to production when ready.",
        action="overview",
    )
    plan = resolve_branch_plan(project)
    if plan.isolated and plan.work_branch:
        await create_notification(
            session,
            project.id,
            NotificationType.MERGE_READY,
            "Merge to main?",
            (
                f"Factory work is on `{plan.work_branch}`. Your production branch "
                f"(`{plan.base_branch}`) is unchanged. Merge when you're ready, "
                f"or keep iterating on the factory branch."
            ),
            action="merge",
        )
        await create_input_request(
            session,
            project.id,
            agent_id="pipeline",
            role="reviewer",
            question=(
                f"Merge factory branch `{plan.work_branch}` into `{plan.base_branch}` now?"
            ),
            default_decision="Keep on factory branch for now",
            context_detail=(
                "Use the dashboard Merge to main button when you want production updated. "
                "The factory never merges without your approval."
            ),
            options=["Merge to main now", "Keep on factory branch"],
            risk="destructive",
        )
    return True


async def stage_production(ex: "PipelineExecutor", session, project, context) -> bool:
    meta = ex.workspace.load_metadata(project.id)
    origin = context.get("preview_origin") or await get_preview_origin(session)
    preview = preview_from_metadata(meta, origin=origin, project_id=project.id)
    prod_url = preview["preview_url"] or ""
    port = preview.get("preview_port") or context.get("staging_port")

    previous = await session.execute(
        select(DeploymentRow.image_tag)
        .where(
            DeploymentRow.project_id == project.id,
            DeploymentRow.environment == "production",
            DeploymentRow.status == "running",
        )
        .order_by(DeploymentRow.created_at.desc())
        .limit(1)
    )
    previous_row = previous.first()

    dep = DeploymentRow(
        project_id=project.id,
        environment="production",
        image_tag=project.image_tag or context.get("image_tag", ""),
        url=prod_url,
        port=port,
        status="running",
        previous_tag=previous_row[0] if previous_row else None,
    )
    session.add(dep)
    await session.commit()

    meta["production_url"] = prod_url
    meta["preview_type"] = "production"
    from app.services.self_propelling import get_self_propelling_settings, save_self_propelling_settings

    if not get_self_propelling_settings(project.id, ex.workspace).get("enabled"):
        save_self_propelling_settings(project.id, enabled=True, workspace=ex.workspace)
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[post-production] Self-propelling development enabled — automatic improvement cycles will run",
        )
    ex.workspace.save_metadata(project.id, meta)

    await ex.emit(
        session,
        EventType.DEPLOYMENT_FINISHED,
        project.id,
        payload={"environment": "production", "url": prod_url},
    )
    await ex.transition(session, project, advance_project(ProjectState.REVIEW))
    await create_notification(
        session,
        project.id,
        NotificationType.PROJECT_FINISHED,
        "Project deployed to production",
        f"{project.name} is live at {prod_url or 'production'}",
        action="overview",
    )
    return True
