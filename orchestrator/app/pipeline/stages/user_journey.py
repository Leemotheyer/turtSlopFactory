"""User journey testing: simulate a human exercising the app before production review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings
from app.models import AgentRole

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_user_journey(ex: "PipelineExecutor", session, project, context) -> bool:
    if not context.get("effective_user_journey_enabled", settings.user_journey_testing_enabled):
        context["user_journey_complete"] = True
        return True

    if not ex.runner.docker_available() or not context.get("preview_upstream"):
        from app.artifacts.schemas import UserJourneyReport
        from app.services.user_journey_testing import persist_user_journey_results

        report = UserJourneyReport(
            passed=True,
            notes="Skipped — no live preview container to exercise (simulated or offline deploy)",
        )
        await persist_user_journey_results(ex.workspace, project.id, report)
        context["user_journey_report"] = report.model_dump()
        context["user_journey_passed"] = True
        context["user_journey_complete"] = True
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            "[user_journey] Skipped — no reachable preview_upstream",
        )
        return True

    task = await ex.create_task(
        session,
        project.id,
        "User journey testing",
        "Exercise the live staging preview like a real user and verify core flows",
        AgentRole.TESTER,
    )

    ok, output = await ex.runner._tester(
        project.id, {**context, "test_stage": "user_journey"}
    )

    report_raw = None
    if "user-journey-report.json" in ex.workspace.list_artifacts(project.id):
        report_raw = ex.workspace.read_artifact(project.id, "user-journey-report.json")
    from app.artifacts.parsing import parse_agent_json
    from app.artifacts.schemas import UserJourneyReport

    report = parse_agent_json(UserJourneyReport, report_raw) or UserJourneyReport()
    context["user_journey_report"] = report.model_dump()
    context["user_journey_passed"] = report.passed

    from app.services.evidence import record_evidence
    from app.services.memory import record_known_issues

    for finding in report.blocking_findings:
        await record_evidence(
            session,
            project.id,
            kind="user_journey",
            reference=finding.title[:120],
            passed=False,
            payload={
                "category": finding.category,
                "severity": finding.severity,
                "description": finding.description[:1000],
            },
        )
    if report.ux_improvements:
        await record_known_issues(
            session,
            project.id,
            [
                {
                    "description": f"{f.title}: {f.description[:400]}",
                    "severity": f.severity,
                    "source": "user_journey_ux",
                }
                for f in report.ux_improvements
            ],
        )

    step_summary = f"{sum(1 for s in report.steps if s.success)}/{len(report.steps)} steps succeeded"
    ux_count = len(report.ux_improvements)
    summary = (
        f"{step_summary}; {len(report.blocking_findings)} blocking, "
        f"{ux_count} UX improvement(s) noted for future iterations"
    )

    passed = report.passed and ok
    await ex.complete_task(session, task, passed, summary or output)
    await ex._log_progress(
        session,
        project.id,
        "user_journey",
        "User journey testing " + ("passed" if passed else "found blocking issues"),
        summary,
        detail="\n".join(
            f"[{f.severity}] {f.title}: {f.description[:160]}"
            for f in (report.blocking_findings + report.ux_improvements)[:12]
        )
        or None,
    )

    if passed:
        context["user_journey_complete"] = True
        return True

    from app.services.user_journey_testing import format_blocking_failure

    context["last_failure"] = format_blocking_failure(report)
    if not ok and output:
        context["last_failure"] = f"{output}\n\n{context['last_failure']}"
    return False
