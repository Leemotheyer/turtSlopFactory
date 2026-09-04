"""Test stages: unit (substage of IMPLEMENTING), integration, and smoke."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import AgentRole, EventType
from app.services.evidence import record_test_results_evidence, record_probe_evidence

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_unit_testing(ex: "PipelineExecutor", session, project, context) -> bool:
    await ex._ensure_runnable_app(project, context)
    task = await ex.create_task(
        session, project.id, "Unit tests", "Run pytest unit tests", AgentRole.TESTER
    )
    success, output = await ex.runner._tester(project.id, {**context, "test_stage": "unit"})
    await ex.complete_task(session, task, success, output)
    await ex.emit(
        session, EventType.TEST_COMPLETED, project.id, task.id, payload={"passed": success, "stage": "unit"}
    )
    await record_test_results_evidence(session, ex.workspace, project.id, stage="unit")
    if success:
        context["unit_testing_complete"] = True
        await ex._log_progress(
            session,
            project.id,
            "test",
            "Unit tests passed",
            output[:200] if output else "All unit tests green",
        )
    else:
        context["last_failure"] = output
    return success


async def stage_integration_testing(ex: "PipelineExecutor", session, project, context) -> bool:
    task = await ex.create_task(
        session, project.id, "Integration tests", "Run integration tests", AgentRole.TESTER
    )
    success, output = await ex.runner._tester(
        project.id, {**context, "test_stage": "integration"}
    )
    await ex.complete_task(session, task, success, output)
    await ex.emit(
        session,
        EventType.TEST_COMPLETED,
        project.id,
        task.id,
        payload={"passed": success, "stage": "integration"},
    )
    await record_test_results_evidence(session, ex.workspace, project.id, stage="integration")
    if success:
        context["tests_passed"] = True
        await ex._log_progress(
            session,
            project.id,
            "test",
            "Integration tests passed",
            "API workflow validated end-to-end",
        )
    else:
        context["last_failure"] = output
    return success


async def stage_smoke_testing(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.pipeline.resume import preview_type_for_context

    # Staging previews can go cold during long review/fix cycles — ensure the
    # factory-owned container is up before probing health.
    meta = ex.workspace.load_metadata(project.id)
    if ex.runner.docker_available() and meta.get("preview_status") != "running":
        redeployed = await ex._deploy_live_preview(
            session,
            project,
            context,
            preview_type=preview_type_for_context(context),
            notify=False,
        )
        if not redeployed:
            context["last_failure"] = (
                context.get("last_failure")
                or "Smoke test blocked — factory could not restart the live preview"
            )
            return False

    task = await ex.create_task(
        session, project.id, "Smoke tests", "Health check on staging", AgentRole.TESTER
    )

    if ex.runner.docker_available() and context.get("preview_upstream"):
        success, output = await ex.runner._tester(
            project.id, {**context, "test_stage": "smoke"}
        )
    elif ex.runner.docker_available():
        success = False
        output = "Smoke test skipped — live preview is not running"
    else:
        success = True
        output = "Simulated smoke test pass"

    await ex.complete_task(session, task, success, output)
    await ex.emit(
        session,
        EventType.TEST_COMPLETED,
        project.id,
        task.id,
        payload={"passed": success, "stage": "smoke"},
    )
    await record_probe_evidence(
        session,
        project.id,
        probe="smoke_health",
        passed=success,
        detail=output[:1000],
        health_path=context.get("preview_health_path") or "/health",
    )
    if success:
        context["smoke_testing_complete"] = True
        await ex._log_progress(
            session,
            project.id,
            "test",
            "Smoke tests passed",
            output[:200] if output else "Health check OK on staging",
        )
        # Agent-backed acceptance tester (optional): writes tests/acceptance/
        # from the contract, then the factory runs them deterministically.
        await ex._maybe_run_acceptance_tester(session, project, context)
    else:
        context["last_failure"] = output
    return success
