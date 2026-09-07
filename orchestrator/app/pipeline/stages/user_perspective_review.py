"""End-of-cycle user perspective review — suggestions for the next improvement cycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings
from app.models import AgentRole

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_user_perspective_review(ex: "PipelineExecutor", session, project, context) -> bool:
    """Review the product as an end user; store suggestions for the next cycle (non-blocking)."""
    if not context.get(
        "effective_user_perspective_review_enabled",
        settings.user_perspective_review_enabled,
    ):
        context["user_perspective_review_complete"] = True
        return True

    cycle_number = int(context.get("improvement_cycle_number") or 0)
    cycle_label = f"improvement cycle {cycle_number}" if cycle_number else "initial build"

    if not ex.runner.docker_available() or not context.get("preview_upstream"):
        from app.artifacts.schemas import UserPerspectiveReviewReport
        from app.services.user_perspective_review import persist_user_perspective_review

        report = UserPerspectiveReviewReport(
            passed=True,
            summary="Skipped — no live preview to review",
            notes="No preview_upstream available",
        )
        await persist_user_perspective_review(
            ex.workspace, project.id, report, cycle_number=cycle_number
        )
        context["user_perspective_review_complete"] = True
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[user_perspective] Skipped — no reachable preview",
        )
        return True

    from app.services.product_enrichment import audit_live_preview
    from app.services.user_perspective_review import (
        parse_user_perspective_review,
        persist_user_perspective_review,
        run_local_user_perspective_review,
    )

    context["preview_audit"] = context.get("preview_audit") or await audit_live_preview(context)

    task = await ex.create_task(
        session,
        project.id,
        "User perspective review",
        f"Review the product as an end user at the end of {cycle_label}",
        AgentRole.TESTER,
    )

    repo = ex.workspace.repo_dir(project.id)
    review_context = {
        **context,
        "test_stage": "user_perspective_review",
        "cycle_label": cycle_label,
    }

    report = None
    from app.services.cursor_connection import get_api_key
    from app.database import SessionLocal
    from app.services.factory_settings import get_agent_backend

    try:
        async with SessionLocal() as db_session:
            backend = await get_agent_backend(db_session)
            api_key = await get_api_key(db_session)
    except Exception:
        backend = "local"
        api_key = None

    if backend != "local" and api_key and context.get("post_production") and improvement_cycle > 0 and getattr(
        ex.runner, "_cursor_eligible", lambda *_: False
    )(AgentRole.TESTER, review_context):
        run = await ex.runner.run(
            AgentRole.TESTER,
            project.id,
            task.id,
            str(repo),
            review_context,
        )
        artifact_raw = None
        if "user-perspective-review.json" in ex.workspace.list_artifacts(project.id):
            artifact_raw = ex.workspace.read_artifact(project.id, "user-perspective-review.json")
        report = parse_user_perspective_review(artifact_raw) or parse_user_perspective_review(run.output)
        summary = run.output[:500] if run.output else "LLM user perspective review"
        await ex.complete_task(
            session,
            task,
            True,
            summary,
            agent_id=run.agent_id or None,
            cursor_url=run.cursor_url,
        )
    else:
        report = await run_local_user_perspective_review(ex.workspace, project.id, review_context)
        await ex.complete_task(
            session,
            task,
            True,
            report.summary,
        )

    if report is None:
        report = await run_local_user_perspective_review(ex.workspace, project.id, review_context)

    await persist_user_perspective_review(
        ex.workspace, project.id, report, cycle_number=cycle_number
    )
    context["user_perspective_review_report"] = report.model_dump()

    from app.services.memory import record_known_issues

    if report.suggestions:
        await record_known_issues(
            session,
            project.id,
            [
                {
                    "description": f"[{s.category}] {s.title}: {s.description[:400]}",
                    "severity": s.priority,
                    "source": "user_perspective_review",
                }
                for s in report.suggestions[:15]
            ],
        )

    suggestion_summary = ", ".join(s.title[:40] for s in report.suggestions[:5])
    await ex._log_progress(
        session,
        project.id,
        "user_perspective",
        f"User perspective review — {len(report.suggestions)} suggestion(s) for next cycle",
        report.summary,
        detail=suggestion_summary or None,
    )
    ex.workspace.append_log(
        project.id,
        "pipeline.log",
        f"[user_perspective] {len(report.suggestions)} suggestion(s) stored for next cycle",
    )

    context["user_perspective_review_complete"] = True
    return True
