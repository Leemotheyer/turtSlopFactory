"""Autonomous enrichment passes (pre-integration, pre-review, post-production)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.config import settings
from app.models import AgentRole
from app.services.product_enrichment import (
    audit_live_preview,
    enrichment_change_summary,
    local_enrichment_plan,
    parse_enrichment_plan,
    resolve_feature_scope,
)
from app.services.self_propelling import (
    check_token_budget,
    record_audit_fingerprint,
    should_skip_architect,
)
from app.services.work_planner import _slugify, plan_from_enrichment_features

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def run_enrichment_passes(
    ex: "PipelineExecutor",
    session,
    project,
    context: dict,
    *,
    max_passes: int,
    completion_key: str,
    log_prefix: str,
    completed_slugs_key: str = "enrichment_completed",
    passes_completed_key: str = "enrichment_passes_completed",
    token_budget: bool = False,
    skip_unchanged_audit: bool = False,
) -> bool:
    from app.pipeline.stages.implementing import run_developer_units, stage_fix_from_failure

    if context.get(completion_key):
        return True

    await ex._refresh_context(session, project, context)
    await ex._deploy_live_preview(session, project, context, preview_type="dev", notify=False)

    passes_done = int(context.get(passes_completed_key) or 0)
    completed_slugs: set[str] = set(context.get(completed_slugs_key) or [])
    context["max_enrichment_passes"] = max_passes
    if log_prefix == "post-production":
        context["max_features_per_pass"] = settings.post_production_features_per_pass
    else:
        context["max_features_per_pass"] = settings.max_features_per_enrichment_pass

    if max_passes <= 0:
        context[completion_key] = True
        ex._save_enrichment_progress(project.id, None)
        return True

    while passes_done < max_passes:
        pass_number = passes_done + 1
        if token_budget:
            budget_ok, budget_msg = await check_token_budget(session, project.id, ex.workspace)
            if not budget_ok:
                ex.workspace.append_log(
                    project.id,
                    "pipeline.log",
                    f"[{log_prefix}] Stopping enrichment — {budget_msg}",
                )
                await ex._log_progress(
                    session,
                    project.id,
                    "enrichment",
                    "Token budget reached",
                    budget_msg,
                )
                break

        context["enrichment_pass"] = pass_number
        ex._save_pipeline_substage(
            project.id,
            {
                "gate": project.state,
                "step": "enrichment",
                "phase": log_prefix,
                "current_pass": pass_number,
                "max_passes": max_passes,
                "passes_completed": passes_done,
            },
        )
        ex._save_enrichment_progress(
            project.id,
            {
                "phase": log_prefix,
                "current_pass": pass_number,
                "max_passes": max_passes,
                "passes_completed": passes_done,
                "status": "auditing",
            },
        )
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[{log_prefix}] Starting enrichment pass {pass_number}/{max_passes}",
        )

        audit = await audit_live_preview(context)
        context["preview_audit"] = audit
        from app.services.user_journey_testing import load_ux_backlog_items

        context["ux_improvement_backlog"] = load_ux_backlog_items(ex.workspace, project.id)
        if skip_unchanged_audit:
            record_audit_fingerprint(project.id, audit, ex.workspace)
        await ex._scan_env_placeholders(session, project, context)
        ex.workspace.write_artifact(
            project.id,
            f"preview-audit-{log_prefix}-pass-{pass_number}.json",
            json.dumps(audit, indent=2),
        )

        task = await ex.create_task(
            session,
            project.id,
            f"Product ideation (pass {pass_number})",
            "Audit the live preview and propose substantial improvements",
            AgentRole.ARCHITECT,
        )
        ideation_context = {
            **context,
            "enrichment_pass": pass_number,
            "incremental": True,
        }
        plan_raw = None
        used_fallback = False
        if skip_unchanged_audit and should_skip_architect(project.id, audit, ex.workspace):
            plan = local_enrichment_plan(
                audit,
                pass_number,
                context.get("notes", []),
                max_passes=max_passes,
                completed_slugs=completed_slugs,
                intake=context.get("intake"),
                ux_backlog=context.get("ux_improvement_backlog"),
            )
            ex.workspace.write_artifact(
                project.id,
                "enrichment-plan.json",
                json.dumps(plan, indent=2),
            )
            used_fallback = True
            ideation_success = True
            ideation_output = (
                f"[factory] Skipped architect — preview audit unchanged; "
                f"using local plan ({len(plan.get('features') or [])} feature(s))."
            )
            await ex.complete_task(session, task, ideation_success, ideation_output)
        else:
            run = await ex.runner.run(
                AgentRole.ARCHITECT,
                project.id,
                task.id,
                str(ex.workspace.repo_dir(project.id)),
                ideation_context,
            )
            repo_plan = ex.workspace.repo_dir(project.id) / "enrichment-plan.json"
            if repo_plan.is_file():
                plan_raw = repo_plan.read_text(encoding="utf-8")
            elif "enrichment-plan.json" in ex.workspace.list_artifacts(project.id):
                plan_raw = ex.workspace.read_artifact(project.id, "enrichment-plan.json")
            plan = parse_enrichment_plan(plan_raw or run.output)
            if not plan.get("features"):
                plan = local_enrichment_plan(
                    audit,
                    pass_number,
                    context.get("notes", []),
                    max_passes=max_passes,
                    completed_slugs=completed_slugs,
                    intake=context.get("intake"),
                    ux_backlog=context.get("ux_improvement_backlog"),
                )
                ex.workspace.write_artifact(
                    project.id,
                    "enrichment-plan.json",
                    json.dumps(plan, indent=2),
                )
                used_fallback = True

            ideation_success = run.success or used_fallback
            ideation_output = run.output
            if used_fallback and not run.success:
                ideation_output = (
                    f"{run.output}\n\n[factory] Applied local enrichment plan from preview audit "
                    f"({len(plan.get('features') or [])} feature(s))."
                ).strip()
            elif used_fallback:
                ideation_output = (
                    f"{run.output}\n\n[factory] Cloud reply had no parseable plan — used audit fallback "
                    f"({len(plan.get('features') or [])} feature(s))."
                ).strip()

            await ex.complete_task(
                session,
                task,
                ideation_success,
                ideation_output,
                agent_id=run.agent_id or None,
                cursor_url=run.cursor_url,
            )
            if skip_unchanged_audit:
                record_audit_fingerprint(project.id, audit, ex.workspace)

        request_input = context.get("request_input")
        intake = context.get("intake") or {}
        if request_input:
            for feat in plan.get("features") or []:
                if not isinstance(feat, dict):
                    continue
                title = str(feat.get("title") or "feature")
                description = str(feat.get("description") or title)
                scope = resolve_feature_scope(
                    title,
                    description,
                    context.get("notes"),
                    intake=intake,
                    declared_scope=feat.get("scope"),
                )
                feat["scope"] = scope
                if scope != "uncertain":
                    continue
                await request_input(
                    agent_id="enrichment",
                    role="architect",
                    question=(
                        f"The factory wants to add “{title}”. This may be out of scope — implement it?"
                    ),
                    context_detail=description,
                    options=["Yes, implement it", "Skip for now — not in v1 scope"],
                    default_decision="Skip for now — not in v1 scope",
                    task_id=task.id,
                )

        await ex._refresh_context(session, project, context)
        units = plan_from_enrichment_features(
            plan.get("features") or [],
            context.get("notes", []),
            context.get("input_responses", []),
            completed_slugs=completed_slugs,
            intake=intake,
        )
        if not units:
            reason = plan.get("stop_reason") or "no in-scope improvements"
            ex.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[{log_prefix}] Enrichment complete: {reason}",
            )
            break

        change_summary = enrichment_change_summary(units)
        ex.workspace.write_artifact(
            project.id,
            f"enrichment-changelog-pass-{pass_number}.json",
            json.dumps(
                {
                    "pass": pass_number,
                    "max_passes": max_passes,
                    "features_planned": plan.get("features") or [],
                    "work_units": [{"title": u.title, "feature_id": u.feature_id} for u in units],
                    "change_summary": change_summary,
                },
                indent=2,
            ),
        )
        summary_preview = "; ".join(change_summary[:6])
        if len(change_summary) > 6:
            summary_preview += f" (+{len(change_summary) - 6} more)"
        await ex._log_progress(
            session,
            project.id,
            "enrichment",
            f"Enrichment pass {pass_number}: implementing {len(units)} work unit(s)",
            summary_preview,
            detail="\n".join(change_summary),
        )
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[{log_prefix}] Pass {pass_number} plan: {summary_preview}",
        )

        success, output = await run_developer_units(
            ex, session, project, context, units, command="enrichment_implement"
        )
        if not success:
            context["last_failure"] = output
            for _ in range(settings.enrichment_fix_attempts_per_pass):
                fixed = await stage_fix_from_failure(ex, session, project, context)
                if not fixed:
                    return False
                success, output = await run_developer_units(
                    ex, session, project, context, units, command="enrichment_fix"
                )
                if success:
                    break
            if not success:
                context["last_failure"] = output
                return False

        test_task = await ex.create_task(
            session,
            project.id,
            f"Tests after enrichment pass {pass_number}",
            "Run pytest after enrichment",
            AgentRole.TESTER,
        )
        test_ok, test_output = await ex.runner._tester(
            project.id, {**context, "test_stage": "unit"}
        )
        await ex.complete_task(session, test_task, test_ok, test_output)
        if not test_ok:
            context["last_failure"] = test_output
            return False

        await ex._deploy_live_preview(session, project, context, preview_type="dev", notify=False)
        audit = await audit_live_preview(context)
        context["preview_audit"] = audit

        qa_task = await ex.create_task(
            session,
            project.id,
            f"Product QA (pass {pass_number})",
            "Evaluate live preview quality",
            AgentRole.TESTER,
        )
        qa_ok, qa_output = await ex.runner._tester(
            project.id, {**context, "test_stage": "product_qa"}
        )
        await ex.complete_task(session, qa_task, qa_ok, qa_output)
        context["product_qa"] = qa_output
        context["product_qa_passed"] = qa_ok

        from app.services.intake_contract import intake_has_product_scope

        if not qa_ok and intake_has_product_scope(context.get("intake")):
            context["last_failure"] = (
                "Product QA failed — intake capabilities must work on the live preview "
                "before the factory can continue.\n\n"
                f"{qa_output[:3000]}"
            )
            return False

        passes_done += 1
        context[passes_completed_key] = passes_done
        for feat in plan.get("features") or []:
            if isinstance(feat, dict):
                slug = _slugify(str(feat.get("id") or feat.get("title") or ""))
                if slug:
                    completed_slugs.add(slug)
        for unit in units:
            if unit.feature_id:
                completed_slugs.add(unit.feature_id)
        context[completed_slugs_key] = sorted(completed_slugs)
        ex._save_enrichment_progress(
            project.id,
            {
                "phase": log_prefix,
                "current_pass": pass_number,
                "max_passes": max_passes,
                "passes_completed": passes_done,
                "status": "complete",
            },
        )
        await ex._log_progress(
            session,
            project.id,
            "enrichment",
            f"Enrichment pass {pass_number} complete",
            f"Implemented {len(units)} work unit(s) ({len(change_summary)} deliverable(s)); "
            f"QA {'passed' if qa_ok else 'noted issues'}",
            detail="\n".join(change_summary),
        )

    context[completion_key] = True
    ex._save_enrichment_progress(project.id, None)
    ex._save_pipeline_substage(project.id, None)
    return True


async def stage_autonomous_enrichment(ex: "PipelineExecutor", session, project, context) -> bool:
    max_passes = ex._resolve_max_enrichment_passes(project)
    if max_passes <= 0:
        context["enrichment_complete"] = True
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[enrichment] Skipped — project enrichment iterations set to 0",
        )
        return True
    ok = await run_enrichment_passes(
        ex,
        session,
        project,
        context,
        max_passes=max_passes,
        completion_key="enrichment_complete",
        log_prefix="enrichment",
    )
    if ok:
        context["enrichment_complete"] = True
    return ok


async def stage_post_smoke_enrichment(ex: "PipelineExecutor", session, project, context) -> bool:
    ok = await run_enrichment_passes(
        ex,
        session,
        project,
        context,
        max_passes=1,
        completion_key="post_smoke_enrichment_complete",
        log_prefix="pre-review",
    )
    if ok:
        context["post_smoke_enrichment_complete"] = True
    return ok
