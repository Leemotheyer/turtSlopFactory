"""Adversarial verification: an independent agent tries to falsify acceptance claims.

The adversary has the opposite objective from the implementer: probe the live
staging preview (malformed input, missing auth, concurrency, boundary values)
and produce evidence of failure. It never fixes anything. Findings are recorded
as known issues + failing evidence; high-severity findings fail the gate and
feed the normal fix loop.

Requires an LLM backend (Cursor); with the deterministic local backend the
stage runs a bounded deterministic abuse probe instead.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

from app.artifacts.parsing import parse_agent_json
from app.artifacts.schemas import AdversaryReport
from app.config import settings
from app.models import AgentRole

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor


async def stage_adversary(ex: "PipelineExecutor", session, project, context) -> bool:
    if not context.get("effective_adversary_enabled", settings.adversary_enabled):
        context["adversary_complete"] = True
        return True

    task = await ex.create_task(
        session,
        project.id,
        "Adversarial verification",
        "Attempt to disprove that the app satisfies its acceptance criteria",
        AgentRole.ADVERSARY,
    )

    report_path = ex.workspace.artifacts_dir(project.id) / "adversary-report.json"
    if report_path.exists():
        report_path.unlink()

    run = await ex.runner.run(
        AgentRole.ADVERSARY,
        project.id,
        task.id,
        str(ex.workspace.repo_dir(project.id)),
        context,
    )

    raw = None
    if "adversary-report.json" in ex.workspace.list_artifacts(project.id):
        raw = ex.workspace.read_artifact(project.id, "adversary-report.json")
    agent_report = parse_agent_json(AdversaryReport, raw or run.output)

    # The deterministic abuse probe always runs — it is the floor; an
    # LLM-backed adversary adds findings on top of it.
    probe_report = await _local_abuse_probe(context)

    findings = list(probe_report.findings)
    seen = {f.description.strip().lower() for f in findings}
    if agent_report is not None:
        for finding in agent_report.findings:
            key = finding.description.strip().lower()
            if key and key not in seen:
                findings.append(finding)
                seen.add(key)

    report = AdversaryReport(
        findings=findings,
        notes="; ".join(
            part
            for part in (
                probe_report.notes,
                agent_report.notes if agent_report else "",
            )
            if part
        ),
    )
    ex.workspace.write_artifact(
        project.id,
        "adversary-report.json",
        report.model_dump_json(indent=2),
    )

    high = [f for f in findings if f.severity == "high"]

    from app.services.evidence import record_evidence
    from app.services.memory import record_known_issues

    await record_known_issues(
        session,
        project.id,
        [
            {
                "description": f.description,
                "severity": f.severity,
                "source": "adversary",
            }
            for f in findings
        ],
    )
    for finding in findings:
        await record_evidence(
            session,
            project.id,
            kind="adversary",
            reference=finding.requirement_id or "general",
            passed=False,
            payload={"severity": finding.severity, "description": finding.description[:1000]},
            requirement_key=finding.requirement_id,
        )

    summary = (
        f"{len(findings)} finding(s), {len(high)} high severity"
        if findings
        else "No exploitable failures found"
    )
    passed = not high
    await ex.complete_task(session, task, passed, summary)
    await ex._log_progress(
        session,
        project.id,
        "adversary",
        "Adversarial verification " + ("passed" if passed else "found blocking issues"),
        summary,
        detail="\n".join(f"[{f.severity}] {f.description[:200]}" for f in findings[:10]) or None,
    )

    if passed:
        context["adversary_complete"] = True
        return True

    context["last_failure"] = (
        "Adversarial verification found blocking failures. Fix these without "
        "weakening the tests:\n\n"
        + "\n".join(
            f"- [{f.severity}] ({f.requirement_id or 'general'}) {f.description[:300]}"
            for f in high[:8]
        )
    )
    return False


async def _local_abuse_probe(context: dict) -> AdversaryReport:
    """Deterministic adversary fallback: malformed payloads and boundary probes."""
    from app.artifacts.schemas import AdversaryFinding

    upstream = context.get("preview_upstream") or ""
    findings: list[AdversaryFinding] = []
    if not upstream:
        return AdversaryReport(findings=[], notes="No live preview to probe")

    base = upstream.rstrip("/")
    probes = [
        ("POST", "/api/items", {"content": b"not json", "headers": {"content-type": "application/json"}},
         "Malformed JSON body should return 4xx, not 5xx"),
        ("POST", "/api/items", {"json": {}}, "Empty payload should be rejected with 422"),
        ("GET", "/api/items/999999999", {}, "Unknown id should return 404, not 5xx"),
        ("GET", "/api/items/not-a-number", {}, "Non-numeric id should return 4xx, not 5xx"),
    ]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for method, path, kwargs, expectation in probes:
                url = f"{base}{path}"
                try:
                    response = await client.request(method, url, **kwargs)
                except httpx.HTTPError:
                    continue
                if response.status_code >= 500:
                    findings.append(
                        AdversaryFinding(
                            severity="high",
                            description=(
                                f"{method} {path} returned {response.status_code} — {expectation}"
                            ),
                        )
                    )
    except Exception as exc:  # pragma: no cover — network variance
        return AdversaryReport(findings=findings, notes=f"Probe aborted: {exc}")

    return AdversaryReport(
        findings=findings,
        notes=f"Deterministic abuse probe against {base} ({len(probes)} probes)",
    )
