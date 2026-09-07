"""End-of-cycle user perspective review — suggestions for the next improvement cycle.

Runs after testing at the end of each build or self-propelling cycle. The agent
reviews the product as an end user would and records non-blocking improvement
ideas (bugs, features, UI rework, cleanup, etc.) in a cumulative backlog that
feeds the next cycle's enrichment planning.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.artifacts.schemas import CycleImprovementSuggestion, UserPerspectiveReviewReport
from app.services.intake_contract import intake_capability_lines
from app.services.product_enrichment import audit_live_preview
from app.services.user_journey_testing import load_ux_backlog_items, run_user_journey_tests

_VALID_CATEGORIES = frozenset({"bug_fix", "feature", "cleanup", "ui", "expansion", "other"})
_VALID_PRIORITIES = frozenset({"high", "medium", "low"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower().strip())[:48].strip("-")
    return slug or "improvement"


def _read_artifact_text(workspace, project_id: UUID, name: str, limit: int = 8000) -> str:
    if name not in workspace.list_artifacts(project_id):
        return ""
    try:
        return (workspace.read_artifact(project_id, name) or "")[:limit]
    except OSError:
        return ""


def build_review_context(workspace, project_id: UUID, context: dict) -> dict[str, Any]:
    """Gather signals the user-perspective agent should consider."""
    requirements = _read_artifact_text(workspace, project_id, "requirements.md")
    contract = _read_artifact_text(workspace, project_id, "project-contract.json")
    product_qa = _read_artifact_text(workspace, project_id, "product-qa.json", 4000)
    intake = context.get("intake") or {}
    return {
        "preview_upstream": context.get("preview_upstream") or context.get("preview_url") or "",
        "requirements_excerpt": requirements[:4000],
        "contract_excerpt": contract[:3000],
        "product_qa_excerpt": product_qa[:2000],
        "intake_capabilities": intake_capability_lines(intake)[:12],
        "cycle_number": int(context.get("improvement_cycle_number") or 0),
        "description": (context.get("description") or context.get("original_description") or "")[:1500],
    }


async def run_local_user_perspective_review(
    workspace,
    project_id: UUID,
    context: dict,
) -> UserPerspectiveReviewReport:
    """Deterministic user-perspective review when no LLM agent is available."""
    review_ctx = build_review_context(workspace, project_id, context)
    audit = context.get("preview_audit")
    if not audit:
        audit = await audit_live_preview(context)
        context["preview_audit"] = audit

    journey = context.get("user_journey_report")
    if not journey:
        journey_report = await run_user_journey_tests(context)
        journey = journey_report.model_dump()
        context["user_journey_report"] = journey

    suggestions: list[CycleImprovementSuggestion] = []

    for finding in journey.get("ux_improvements") or []:
        if not isinstance(finding, dict):
            continue
        title = str(finding.get("title") or "").strip()
        if len(title) < 6:
            continue
        suggestions.append(
            CycleImprovementSuggestion(
                title=title,
                description=str(finding.get("description") or title)[:500],
                category="ui",
                priority="medium" if finding.get("severity") != "high" else "high",
            )
        )

    for issue in audit.get("issues") or []:
        text = str(issue).strip()
        if len(text) < 8:
            continue
        suggestions.append(
            CycleImprovementSuggestion(
                title=f"Fix: {text[:72]}",
                description=text[:500],
                category="bug_fix",
                priority="high",
            )
        )

    if not audit.get("has_html_ui"):
        suggestions.append(
            CycleImprovementSuggestion(
                title="Build a complete browser UI",
                description=(
                    "Users expect a polished web interface with navigation, forms, and lists — "
                    "not API-only or placeholder pages."
                ),
                category="feature",
                priority="high",
            )
        )
    elif not audit.get("mobile_friendly"):
        suggestions.append(
            CycleImprovementSuggestion(
                title="Improve mobile layout",
                description="Add responsive CSS and viewport meta so the app works on phone screens.",
                category="ui",
                priority="medium",
            )
        )

    if audit.get("has_html_ui") and not audit.get("responsive_signals"):
        suggestions.append(
            CycleImprovementSuggestion(
                title="Add responsive design",
                description="Use flexible layouts and media queries so content adapts to narrow viewports.",
                category="ui",
                priority="medium",
            )
        )

    capabilities = review_ctx.get("intake_capabilities") or []
    endpoints = audit.get("endpoints") or []
    api_paths = {str(e.get("path", "")) for e in endpoints if e.get("ok")}
    if capabilities and not any("/api/" in p for p in api_paths):
        suggestions.append(
            CycleImprovementSuggestion(
                title="Implement intake capabilities end-to-end",
                description=(
                    "Intake promises: "
                    + "; ".join(capabilities[:3])
                    + ". Wire API routes and UI screens for each."
                ),
                category="expansion",
                priority="high",
            )
        )

    if audit.get("has_html_ui") and audit.get("health_ok"):
        suggestions.append(
            CycleImprovementSuggestion(
                title="Add search and filter on main lists",
                description="Let users find items quickly with search, sort, and filter controls.",
                category="feature",
                priority="medium",
            )
        )
        suggestions.append(
            CycleImprovementSuggestion(
                title="Settings or preferences page",
                description="Give users a dedicated place to configure the app or their profile.",
                category="feature",
                priority="medium",
            )
        )

    if not suggestions:
        suggestions.append(
            CycleImprovementSuggestion(
                title="Expand core user workflows",
                description=(
                    "Review requirements.md and add the next most valuable capability users would notice."
                ),
                category="expansion",
                priority="medium",
            )
        )

    # Dedupe by title
    seen: set[str] = set()
    unique: list[CycleImprovementSuggestion] = []
    for item in suggestions:
        key = item.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    cycle = review_ctx.get("cycle_number") or 0
    summary = (
        f"Recorded {len(unique)} improvement suggestion(s) for cycle {cycle or 'build'} "
        f"from preview audit and user journey signals."
    )
    return UserPerspectiveReviewReport(
        passed=True,
        summary=summary,
        suggestions=unique[:20],
        notes=review_ctx.get("description", "")[:300],
    )


def merge_cycle_improvement_backlog(
    existing_raw: str | None,
    new_items: list[CycleImprovementSuggestion],
    *,
    cycle_number: int = 0,
) -> dict[str, Any]:
    """Merge user-perspective suggestions into a cumulative backlog."""
    backlog: dict[str, Any] = {"items": [], "updated_at": _utc_now()}
    if existing_raw:
        try:
            parsed = json.loads(existing_raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                backlog["items"] = list(parsed["items"])
        except json.JSONDecodeError:
            pass

    seen = {
        str(item.get("title", "")).strip().lower()
        for item in backlog["items"]
        if isinstance(item, dict)
    }
    for suggestion in new_items:
        title = suggestion.title.strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        category = suggestion.category if suggestion.category in _VALID_CATEGORIES else "other"
        priority = suggestion.priority if suggestion.priority in _VALID_PRIORITIES else "medium"
        backlog["items"].append(
            {
                "id": _slug_id(title),
                "title": title,
                "description": suggestion.description[:500],
                "category": category,
                "priority": priority,
                "source": "user_perspective_review",
                "cycle_number": cycle_number,
                "created_at": _utc_now(),
            }
        )
    backlog["items"] = backlog["items"][-80:]
    backlog["updated_at"] = _utc_now()
    return backlog


async def persist_user_perspective_review(
    workspace,
    project_id: UUID,
    report: UserPerspectiveReviewReport,
    *,
    cycle_number: int = 0,
) -> None:
    workspace.write_artifact(
        project_id,
        "user-perspective-review.json",
        report.model_dump_json(indent=2),
    )
    existing = None
    if "cycle-improvement-backlog.json" in workspace.list_artifacts(project_id):
        existing = workspace.read_artifact(project_id, "cycle-improvement-backlog.json")
    backlog = merge_cycle_improvement_backlog(existing, report.suggestions, cycle_number=cycle_number)
    workspace.write_artifact(
        project_id,
        "cycle-improvement-backlog.json",
        json.dumps(backlog, indent=2),
    )


def load_cycle_improvement_backlog(workspace, project_id: UUID) -> list[dict[str, Any]]:
    if "cycle-improvement-backlog.json" not in workspace.list_artifacts(project_id):
        return []
    try:
        raw = workspace.read_artifact(project_id, "cycle-improvement-backlog.json") or "{}"
        data = json.loads(raw)
        items = data.get("items") if isinstance(data, dict) else []
        return [item for item in items if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []


def load_all_improvement_backlog_items(workspace, project_id: UUID) -> list[dict[str, Any]]:
    """UX backlog + cycle improvement backlog for enrichment planning."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (load_ux_backlog_items(workspace, project_id), load_cycle_improvement_backlog(workspace, project_id)):
        for item in source:
            title = str(item.get("title") or "").strip().lower()
            if not title or title in seen:
                continue
            seen.add(title)
            items.append(item)
    return items


def parse_user_perspective_review(raw: str | None) -> UserPerspectiveReviewReport | None:
    if not raw:
        return None
    from app.artifacts.parsing import parse_agent_json

    return parse_agent_json(UserPerspectiveReviewReport, raw)
