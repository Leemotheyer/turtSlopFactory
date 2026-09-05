"""Implementation stage: parallel developer agents and fix-from-failure runs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ProjectRow, TaskRow
from app.models import AgentRole, EventType
from app.pipeline.stages import SUBSTAGE_IMPLEMENTING, SUBSTAGE_UNIT_TESTING
from app.services.agent_concurrency import (
    resolve_concurrency_budget,
    wait_for_cursor_capacity,
)
from app.services.change_stats import capture_repo_baseline, compute_change_stats, record_change_stats
from app.services.completed_work import mark_work_unit_complete
from app.services.factory_settings import get_agent_backend
from app.services.work_planner import optimize_work_units

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_fix_from_failure(
    ex: "PipelineExecutor", session: AsyncSession, project: ProjectRow, context: dict
) -> bool:
    """Run a developer pass to fix the last failing stage before retrying."""
    failure = context.get("last_failure")
    if not failure:
        return True

    await ex._ensure_runnable_app(project, context)
    task = await ex.create_task(
        session,
        project.id,
        "Fix failing stage",
        str(failure)[:500],
        AgentRole.DEVELOPER,
    )
    run = await ex.runner.run(
        AgentRole.DEVELOPER,
        project.id,
        task.id,
        str(ex.workspace.repo_dir(project.id)),
        context,
    )
    await ex.complete_task(
        session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
    )
    if not run.success:
        context["last_failure"] = run.output
        ex._persist_last_failure(project.id, context)
        return False

    substage = context.get("failed_substage")
    if substage in (SUBSTAGE_UNIT_TESTING, SUBSTAGE_IMPLEMENTING, None):
        # The developer fix succeeded — clear the stale failure before the
        # preview refresh so an infra-only preview problem (e.g. no docker)
        # does not masquerade as a failed code fix. App-level preview
        # failures re-populate last_failure inside _deploy_live_preview.
        context.pop("last_failure", None)
        from app.pipeline.resume import preview_type_for_context

        preview_ok = await ex._deploy_live_preview(
            session,
            project,
            context,
            preview_type=preview_type_for_context(context),
        )
        return preview_ok or not context.get("last_failure")
    return True


async def run_parallel_developers(
    ex: "PipelineExecutor", session, project, context: dict
) -> tuple[bool, str]:
    from app.pipeline.stages.planning import build_work_plan

    units, plan, budget = await build_work_plan(ex, session, project, context)
    context["work_plan"] = plan

    backend = await get_agent_backend(session)
    if backend == "cursor_cloud":
        budget = await wait_for_cursor_capacity(
            session, min_slots=1, timeout_seconds=600, poll_seconds=20
        )
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[concurrency] {budget.strategy}",
        )

    if budget.max_parallel < 1:
        return False, (
            "No Cursor Cloud agent slots available for parallel implementation. "
            "Wait for running agents to finish or archive idle cloud agents, then retry."
        )

    await ex._ensure_repo_scaffold(project, context)

    task_rows: list[tuple] = []
    for unit in units:
        task = await ex.create_task(
            session,
            project.id,
            unit.title,
            unit.description,
            AgentRole.DEVELOPER,
        )
        task_rows.append((unit, task))

    await ex.emit(
        session,
        EventType.AGENT_COMMAND_STARTED,
        project.id,
        payload={
            "command": "parallel_implement",
            "streams": [u.stream for u in units],
            "count": len(units),
            "max_parallel": budget.max_parallel,
            "active_cursor_agents": budget.active_cursor_agents,
        },
    )

    baseline = capture_repo_baseline(ex.workspace.repo_dir(project.id))
    semaphore = asyncio.Semaphore(budget.max_parallel)

    async def run_unit(unit, task_row: TaskRow) -> tuple[TaskRow, bool, str, str | None, str | None]:
        async with semaphore:
            unit_context = {
                **context,
                "work_stream": unit.stream,
                "work_description": unit.description,
                "feature_id": unit.feature_id,
                "feature_content": unit.feature_content,
            }
            run = await ex.runner.run(
                AgentRole.DEVELOPER,
                project.id,
                task_row.id,
                str(ex.workspace.repo_dir(project.id)),
                unit_context,
            )
            return task_row, run.success, run.output, run.agent_id or None, run.cursor_url

    results = await asyncio.gather(*[run_unit(u, t) for u, t in task_rows])

    outputs: list[str] = []
    all_ok = True
    for (unit, _), (task_row, success, output, agent_id, cursor_url) in zip(task_rows, results):
        await ex.complete_task(
            session,
            task_row,
            success,
            output,
            agent_id=agent_id,
            cursor_url=cursor_url,
        )
        outputs.append(output)
        if success:
            mark_work_unit_complete(ex.workspace, project.id, unit)
        else:
            all_ok = False

    combined = "; ".join(outputs)
    await record_change_stats(
        ex,
        session,
        project,
        baseline,
        label="parallel_implement",
        units=[u for u, _ in task_rows],
        context=context,
        outputs=combined,
    )
    return all_ok, combined


async def run_developer_units(
    ex: "PipelineExecutor",
    session,
    project,
    context: dict,
    units: list,
    *,
    command: str = "parallel_implement",
) -> tuple[bool, str]:
    if not units:
        return True, "No developer tasks"

    budget = await resolve_concurrency_budget(session)
    if not command.startswith("enrichment_"):
        units = optimize_work_units(units, budget.max_parallel)
    backend = await get_agent_backend(session)
    if backend == "cursor_cloud":
        budget = await wait_for_cursor_capacity(
            session, min_slots=1, timeout_seconds=600, poll_seconds=20
        )
        ex.workspace.append_log(project.id, "pipeline.log", f"[concurrency] {budget.strategy}")

    if budget.max_parallel < 1:
        return False, "No Cursor Cloud agent slots available for implementation."

    await ex._ensure_repo_scaffold(project, context)
    task_rows: list[tuple] = []
    for unit in units:
        task = await ex.create_task(
            session,
            project.id,
            unit.title,
            unit.description,
            AgentRole.DEVELOPER,
        )
        task_rows.append((unit, task))

    await ex.emit(
        session,
        EventType.AGENT_COMMAND_STARTED,
        project.id,
        payload={
            "command": command,
            "streams": [u.stream for u in units],
            "count": len(units),
            "max_parallel": budget.max_parallel,
        },
    )

    baseline = capture_repo_baseline(ex.workspace.repo_dir(project.id))
    semaphore = asyncio.Semaphore(budget.max_parallel)

    async def run_unit(unit, task_row: TaskRow) -> tuple[TaskRow, bool, str, str | None, str | None]:
        async with semaphore:
            unit_context = {
                **context,
                "work_stream": unit.stream,
                "work_description": unit.description,
                "feature_id": unit.feature_id,
                "feature_content": unit.feature_content,
                "incremental": True,
            }
            if command.startswith("enrichment_"):
                unit_context["enrichment_command"] = command
                if unit.tier:
                    unit_context["enrichment_tier"] = unit.tier
            run = await ex.runner.run(
                AgentRole.DEVELOPER,
                project.id,
                task_row.id,
                str(ex.workspace.repo_dir(project.id)),
                unit_context,
            )
            return task_row, run.success, run.output, run.agent_id or None, run.cursor_url

    results = await asyncio.gather(*[run_unit(u, t) for u, t in task_rows])
    outputs: list[str] = []
    all_ok = True
    for (unit, _), (task_row, success, output, agent_id, cursor_url) in zip(task_rows, results):
        await ex.complete_task(
            session,
            task_row,
            success,
            output,
            agent_id=agent_id,
            cursor_url=cursor_url,
        )
        outputs.append(output)
        if success:
            mark_work_unit_complete(ex.workspace, project.id, unit)
        else:
            all_ok = False

    combined = "; ".join(outputs)
    stats = compute_change_stats(ex.workspace.repo_dir(project.id), baseline)
    if command.startswith("enrichment_"):
        has_milestone = any(getattr(u, "tier", None) == "milestone" for u in units)
        min_lines = 15 if has_milestone else 5
        min_files = 2 if has_milestone else 1
        if stats["files_changed"] < min_files or stats["lines_changed"] < min_lines:
            all_ok = False
            combined = (
                f"No meaningful code changes detected ({stats['files_changed']} files, "
                f"{stats['lines_changed']} lines). Developers must edit source files — "
                f"JSON plans or chat replies do not count. {combined}"
            )
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[enrichment] {combined[:400]}",
            )
    await record_change_stats(
        ex,
        session,
        project,
        baseline,
        label=command,
        units=[u for u, _ in task_rows],
        context=context,
        outputs=combined,
    )
    return all_ok, combined


async def stage_implementing(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.pipeline.stages.planning import build_work_plan

    await ex._refresh_context(session, project, context)
    units, plan, _budget = await build_work_plan(ex, session, project, context)
    context["work_plan"] = plan
    if not units:
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[feedback] No new implementation work — skipping developer agents",
        )
        context["implementation_complete"] = True
        await ex._log_progress(
            session,
            project.id,
            "implementation",
            "Feedback applied (no new code changes needed)",
            "All note features were already implemented",
        )
        return True

    success, output = await run_parallel_developers(ex, session, project, context)
    if not success:
        context["last_failure"] = output
        return False

    # Developers succeeded — drop any stale failure from earlier attempts so
    # the preview refresh below is judged on its own outcome only.
    context.pop("last_failure", None)

    stream_count = len(context.get("work_plan", {}).get("units", []))
    max_parallel = (context.get("work_plan", {}).get("concurrency") or {}).get("max_parallel")
    parallel_label = (
        f"Parallel implementation ({stream_count} streams, max {max_parallel} concurrent)"
        if max_parallel
        else f"Parallel implementation ({stream_count} agents)"
    )
    await ex._log_progress(
        session,
        project.id,
        "implementation",
        parallel_label,
        output[:300],
    )
    first_preview = ex.workspace.load_metadata(project.id).get("preview_status") != "running"
    preview_ok = await ex._deploy_live_preview(
        session,
        project,
        context,
        preview_type="dev",
        notify=first_preview,
    )
    if not preview_ok and context.get("last_failure"):
        from app.services.diagnosis import diagnose_failure

        preview_diag = diagnose_failure(str(context.get("last_failure")), gate="IMPLEMENTING")
        if preview_diag["error_class"] == "infra":
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                "[preview] Infra-only preview failure during implementation — continuing to unit tests",
            )
            context.pop("last_failure", None)
            context["implementation_complete"] = True
            return True
    context["implementation_complete"] = True
    return preview_ok or not context.get("last_failure")
