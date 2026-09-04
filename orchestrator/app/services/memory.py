"""Persistent engineering memory: decisions, failures, known issues.

Write paths run from the pipeline; the read path produces a bounded prompt
section so agents stop rediscovering the project and repeating failures.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.artifacts.schemas import ArchitectureDecisionDraft
from app.db_models import ArchitectureDecisionRow, FailureRecordRow, KnownIssueRow

logger = logging.getLogger(__name__)

_MEMORY_CHAR_BUDGET = 1800


def _slugify_failure(record_id: UUID) -> str:
    return str(record_id)[:8]


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


async def record_decisions(
    session: AsyncSession,
    project_id: UUID,
    decisions: list[ArchitectureDecisionDraft],
    *,
    agent_role: str = "architect",
) -> int:
    """Store architect decisions, skipping duplicates of existing ones."""
    if not decisions:
        return 0
    result = await session.execute(
        select(ArchitectureDecisionRow.decision).where(
            ArchitectureDecisionRow.project_id == project_id
        )
    )
    existing = {row[0].strip().lower() for row in result}
    added = 0
    for draft in decisions:
        text = (draft.decision or "").strip()
        if not text or text.lower() in existing:
            continue
        session.add(
            ArchitectureDecisionRow(
                project_id=project_id,
                decision=text[:2000],
                reason=(draft.reason or "")[:2000],
                alternatives=[str(a)[:300] for a in draft.alternatives][:10],
                tradeoffs=(draft.tradeoffs or "")[:2000],
                agent_role=agent_role,
            )
        )
        existing.add(text.lower())
        added += 1
    if added:
        await session.commit()
    return added


async def record_failure(
    session: AsyncSession,
    project_id: UUID,
    *,
    gate: str,
    substage: str | None,
    error_class: str,
    summary: str,
    attempt: int,
) -> UUID | None:
    try:
        row = FailureRecordRow(
            project_id=project_id,
            gate=gate,
            substage=substage,
            error_class=error_class,
            summary=summary[:2000],
            attempt=attempt,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id
    except Exception:
        logger.exception("Could not record failure for %s", project_id)
        return None


async def resolve_failures_for_gate(
    session: AsyncSession,
    project_id: UUID,
    gate: str,
    *,
    resolution: str,
) -> int:
    result = await session.execute(
        select(FailureRecordRow).where(
            FailureRecordRow.project_id == project_id,
            FailureRecordRow.gate == gate,
            FailureRecordRow.resolved.is_(False),
        )
    )
    rows = list(result.scalars())
    for row in rows:
        row.resolved = True
        row.resolution = resolution
        row.resolved_at = datetime.utcnow()
        expected = f"test_fix_{_slugify_failure(row.id)}.py"
        row.regression_test = expected
    if rows:
        await session.commit()
    return len(rows)


async def record_known_issues(
    session: AsyncSession, project_id: UUID, issues: list[dict]
) -> int:
    if not issues:
        return 0
    result = await session.execute(
        select(KnownIssueRow.description).where(
            KnownIssueRow.project_id == project_id,
            KnownIssueRow.status == "open",
        )
    )
    existing = {row[0].strip().lower() for row in result}
    added = 0
    for issue in issues:
        description = str(issue.get("description") or "").strip()
        if not description or description.lower() in existing:
            continue
        session.add(
            KnownIssueRow(
                project_id=project_id,
                source=str(issue.get("source") or "tester")[:32],
                severity=str(issue.get("severity") or "medium")[:16],
                description=description[:2000],
            )
        )
        existing.add(description.lower())
        added += 1
    if added:
        await session.commit()
    return added


async def resolve_known_issue(
    session: AsyncSession, project_id: UUID, issue_id: UUID, *, status: str = "fixed"
) -> bool:
    row = await session.get(KnownIssueRow, issue_id)
    if row is None or row.project_id != project_id:
        return False
    row.status = status
    row.resolved_at = datetime.utcnow()
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# Regression-test policy
# ---------------------------------------------------------------------------


async def unresolved_regression_gaps(
    session: AsyncSession, project_id: UUID, *, repo: Path
) -> list[dict]:
    """Resolved app-level failures whose regression test is missing from the repo."""
    result = await session.execute(
        select(FailureRecordRow).where(
            FailureRecordRow.project_id == project_id,
            FailureRecordRow.resolved.is_(True),
            FailureRecordRow.error_class == "app",
        )
    )
    gaps: list[dict] = []
    regression_dir = repo / "tests" / "regression"
    for row in result.scalars():
        expected = row.regression_test or f"test_fix_{_slugify_failure(row.id)}.py"
        if not (regression_dir / expected).is_file():
            gaps.append(
                {
                    "failure_id": _slugify_failure(row.id),
                    "expected_test": expected,
                    "gate": row.gate,
                    "summary": row.summary[:300],
                }
            )
    return gaps


# ---------------------------------------------------------------------------
# Read path (bounded prompt memory)
# ---------------------------------------------------------------------------


async def load_project_memory(
    session: AsyncSession, project_id: UUID, *, gate: str | None = None
) -> dict:
    decisions_result = await session.execute(
        select(ArchitectureDecisionRow)
        .where(ArchitectureDecisionRow.project_id == project_id)
        .order_by(ArchitectureDecisionRow.created_at.desc())
        .limit(5)
    )
    decisions = [
        {"decision": row.decision, "reason": row.reason}
        for row in decisions_result.scalars()
    ]

    issues_result = await session.execute(
        select(KnownIssueRow)
        .where(KnownIssueRow.project_id == project_id, KnownIssueRow.status == "open")
        .order_by(KnownIssueRow.created_at.desc())
        .limit(5)
    )
    issues = [
        {"severity": row.severity, "description": row.description, "source": row.source}
        for row in issues_result.scalars()
    ]

    failures_query = (
        select(FailureRecordRow)
        .where(FailureRecordRow.project_id == project_id)
        .order_by(FailureRecordRow.created_at.desc())
        .limit(5)
    )
    if gate:
        failures_query = (
            select(FailureRecordRow)
            .where(FailureRecordRow.project_id == project_id, FailureRecordRow.gate == gate)
            .order_by(FailureRecordRow.created_at.desc())
            .limit(5)
        )
    failures_result = await session.execute(failures_query)
    failures = [
        {
            "gate": row.gate,
            "error_class": row.error_class,
            "summary": row.summary[:200],
            "attempt": row.attempt,
            "resolved": row.resolved,
        }
        for row in failures_result.scalars()
    ]

    return {"decisions": decisions, "known_issues": issues, "recent_failures": failures}


def format_memory_for_prompt(memory: dict | None) -> str:
    """Render project memory into a hard-budgeted prompt section."""
    if not memory:
        return ""
    lines: list[str] = []
    decisions = memory.get("decisions") or []
    if decisions:
        lines.append("### Standing decisions (do not silently undo)")
        for d in decisions[:4]:
            reason = f" — {d['reason']}" if d.get("reason") else ""
            lines.append(f"- {d['decision']}{reason}")
    issues = memory.get("known_issues") or []
    if issues:
        lines.append("### Open known issues")
        for issue in issues[:4]:
            lines.append(f"- [{issue['severity']}] {issue['description']}")
    failures = memory.get("recent_failures") or []
    unresolved = [f for f in failures if not f.get("resolved")]
    if unresolved:
        lines.append("### Previous failures at this gate (avoid repeating)")
        for f in unresolved[:3]:
            lines.append(f"- [{f['error_class']}] attempt {f['attempt']}: {f['summary']}")
    if not lines:
        return ""
    text = "\n## Project memory\n" + "\n".join(lines)
    if len(text) > _MEMORY_CHAR_BUDGET:
        text = text[: _MEMORY_CHAR_BUDGET - 1] + "…"
    return text
