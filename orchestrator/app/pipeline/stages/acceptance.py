"""Acceptance evaluation: per-requirement verification backed by recorded evidence.

This is the deterministic "Evaluate" step of the pipeline control loop. It does
not use an LLM — it reads the contract requirements and the evidence rows that
earlier stages recorded (test runs, probes, builds) and decides whether every
requirement is verified. Any failed or unverified requirement fails the gate,
which feeds the normal fix loop with a structured report.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.models import AgentRole

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_acceptance(ex: "PipelineExecutor", session, project, context) -> bool:
    from app.services.contracts import get_latest_contract
    from app.services.evidence import evaluate_acceptance, sync_requirements_from_contract
    from app.services.memory import unresolved_regression_gaps

    contract = context.get("contract") or await get_latest_contract(session, project.id)
    if contract is None:
        # No contract (legacy project mid-flight) — nothing to evaluate against.
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[acceptance] No project contract — skipping acceptance evaluation",
        )
        context["acceptance_complete"] = True
        return True
    context["contract"] = contract

    task = await ex.create_task(
        session,
        project.id,
        "Acceptance evaluation",
        "Verify every contract requirement against recorded evidence",
        AgentRole.TESTER,
    )

    await sync_requirements_from_contract(session, project.id, contract)
    report = await evaluate_acceptance(session, project.id, contract)

    # Regression-test policy: resolved app-level failures must reference a
    # passing regression test (tests/regression/test_<failure>.py).
    regression_gaps = await unresolved_regression_gaps(
        session, project.id, repo=ex.workspace.repo_dir(project.id)
    )
    if regression_gaps:
        report["regression_gaps"] = regression_gaps

    ex.workspace.write_artifact(
        project.id, "acceptance-report.json", json.dumps(report, indent=2)
    )
    context["acceptance_report"] = report

    verified = report.get("verified", 0)
    total = report.get("total", 0)
    passed = bool(report.get("all_verified")) and not regression_gaps

    summary = f"{verified}/{total} requirement(s) verified"
    if regression_gaps:
        summary += f"; {len(regression_gaps)} fixed failure(s) missing regression tests"

    await ex.complete_task(session, task, passed, summary)
    await ex._log_progress(
        session,
        project.id,
        "acceptance",
        "Acceptance evaluation " + ("passed" if passed else "failed"),
        summary,
        detail=json.dumps(report.get("requirements", {}), indent=2)[:4000],
    )

    if passed:
        context["acceptance_complete"] = True
        return True

    problems: list[str] = []
    for req_id, entry in (report.get("requirements") or {}).items():
        status = entry.get("status")
        if status in ("failed", "unverified"):
            problems.append(
                f"- {req_id} [{status}] {entry.get('description', '')[:160]}\n"
                f"  acceptance: {'; '.join(entry.get('acceptance') or [])[:300]}\n"
                f"  evidence: {entry.get('evidence_summary') or 'none recorded'}"
            )
    for gap in regression_gaps:
        problems.append(
            f"- Missing regression test for fixed failure `{gap['failure_id']}`: "
            f"add tests/regression/{gap['expected_test']} covering: {gap['summary'][:200]}"
        )

    context["last_failure"] = (
        "Acceptance evaluation failed. Every contract requirement needs verifiable "
        "evidence (a passing test named test_<req_id>_* or a recorded probe).\n\n"
        + "\n".join(problems[:12])
    )
    return False
