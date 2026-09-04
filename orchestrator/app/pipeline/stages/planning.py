"""Planning stage: architect run, project contract, coverage-checked work plan."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from app.models import AgentRole, ProjectState
from app.services.agent_concurrency import (
    concurrency_budget_to_dict,
    resolve_concurrency_budget,
)
from app.services.completed_work import filter_units_for_feedback, load_completed_work
from app.services.static_planning import draft_requirements_from_context
from app.services.work_planner import (
    optimize_work_units,
    plan_parallel_work,
    work_plan_to_dict,
)

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


def ensure_planning_artifacts(ex: "PipelineExecutor", project_id: UUID) -> None:
    """Ensure architect outputs include both requirements and architecture docs."""
    from app.agents.cursor_cloud_runner import _split_requirements_architecture

    artifacts = ex.workspace.list_artifacts(project_id)
    if "architecture.md" in artifacts:
        return
    requirements = (
        ex.workspace.read_artifact(project_id, "requirements.md")
        if "requirements.md" in artifacts
        else None
    )
    if not requirements:
        return
    _, arch = _split_requirements_architecture(requirements)
    if not arch:
        arch = (
            "# Architecture\n\n"
            "See `requirements.md` for the full specification. "
            "This project uses the factory default stack: FastAPI backend, "
            "static web UI, in-memory storage, and Docker deployment.\n"
        )
    ex.workspace.write_artifact(project_id, "architecture.md", arch)
    ex.workspace.append_log(
        project_id,
        "pipeline.log",
        "[planning] Added missing architecture.md from planning output",
    )


async def build_work_plan(ex: "PipelineExecutor", session, project, context: dict):
    from app.services.contracts import ensure_requirement_coverage

    budget = await resolve_concurrency_budget(session)
    raw_units = plan_parallel_work(
        context.get("notes", []),
        project.description,
        repo_analysis=context.get("repo_analysis"),
    )
    if context.get("feedback_iteration"):
        completed = load_completed_work(ex.workspace, project.id)
        repo = ex.workspace.repo_dir(project.id)
        before = len(raw_units)
        raw_units = filter_units_for_feedback(raw_units, completed=completed, repo=repo)
        skipped = before - len(raw_units)
        if skipped:
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[feedback] Skipping {skipped} already-completed work stream(s)",
            )
    units = optimize_work_units(raw_units, budget.max_parallel)

    contract = context.get("contract")
    coverage: dict = {}
    if contract:
        units, coverage = ensure_requirement_coverage(units, contract)
        uncovered_before = coverage.get("added_units") or []
        if uncovered_before:
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                "[planning] Added work unit(s) for uncovered requirement(s): "
                + ", ".join(uncovered_before),
            )

    plan = work_plan_to_dict(units, concurrency_budget_to_dict(budget))
    if coverage:
        plan["requirement_coverage"] = coverage
    if not units and context.get("feedback_iteration"):
        plan["feedback_skip_implementation"] = True
    ex.workspace.append_log(
        project.id,
        "pipeline.log",
        f"[concurrency] {budget.strategy}",
    )
    return units, plan, budget


async def stage_planning(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.services.contracts import (
        contract_from_planning,
        save_contract,
        sync_requirements_from_contract,
        write_contract_artifacts,
    )
    from app.services.system_map import refresh_system_map

    await ex._refresh_context(session, project, context)
    draft = draft_requirements_from_context(
        project.name,
        context.get("original_description") or project.description,
        intake=context.get("intake"),
        repo_analysis=context.get("repo_analysis"),
        global_agent_rules=context.get("global_agent_rules", ""),
        project_agent_rules=context.get("project_agent_rules", ""),
    )
    context["requirements_draft"] = draft
    ex.workspace.write_artifact(project.id, "requirements-draft.md", draft)

    vision = context.get("original_description") or project.description
    task = await ex.create_task(
        session,
        project.id,
        "Architecture planning",
        f"Product vision:\n{vision[:2000]}",
        AgentRole.ARCHITECT,
    )
    run = await ex.runner.run(
        AgentRole.ARCHITECT, project.id, task.id, str(ex.workspace.repo_dir(project.id)), context
    )
    await ex.complete_task(
        session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
    )
    if not run.success:
        context["last_failure"] = run.output
        ex._persist_last_failure(project.id, context)
        return False
    ensure_planning_artifacts(ex, project.id)

    # Project contract: architect output when parseable, deterministic fallback otherwise.
    contract, decisions = contract_from_planning(
        ex.workspace,
        project,
        context,
        architect_output=run.output or "",
    )
    saved = await save_contract(session, project.id, contract, source=contract.source)
    context["contract"] = saved
    write_contract_artifacts(ex.workspace, project.id, saved)
    await sync_requirements_from_contract(session, project.id, saved)
    if decisions:
        from app.services.memory import record_decisions

        await record_decisions(session, project.id, decisions, agent_role="architect")

    refresh_system_map(ex.workspace, project.id, repo_analysis=context.get("repo_analysis"))

    units, plan, budget = await build_work_plan(ex, session, project, context)
    ex.workspace.write_artifact(project.id, "work-plan.json", json.dumps(plan, indent=2))
    context["work_plan"] = plan
    await ex._log_progress(
        session,
        project.id,
        "planning",
        "Architecture planned",
        (
            f"Contract v{saved.version}: {len(saved.requirements)} requirement(s); "
            f"{len(units)} work stream(s), up to {budget.max_parallel} parallel agent(s)"
        ),
    )
    return True
