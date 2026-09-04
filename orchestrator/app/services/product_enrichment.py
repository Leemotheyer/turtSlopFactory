"""Autonomous product enrichment: preview audit, ideation, and scope checks."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.services.work_planner import WorkUnit, _slugify

_SCOPE_UNCERTAIN_KEYWORDS = (
    "payment",
    "stripe",
    "billing",
    "subscription",
    "oauth",
    "sso",
    "saml",
    "email",
    "sms",
    "twilio",
    "sendgrid",
    "multi-tenant",
    "multitenant",
    "admin panel",
    "machine learning",
    "blockchain",
    "crypto",
)

# Substantial pass themes — each pass should feel like a real product milestone.
_ENRICHMENT_PASS_THEMES: dict[int, list[tuple[str, str, str]]] = {
    1: [
        (
            "core-flows",
            "Complete core user journeys",
            "Implement end-to-end flows for the app's primary use case: list/browse views, "
            "create/edit forms with validation, detail pages, and delete with confirmation. "
            "Wire every screen to real API endpoints with loading and error states.",
        ),
        (
            "navigation-shell",
            "App shell & navigation",
            "Add a cohesive layout: header/branding, primary navigation, active route highlighting, "
            "and a settings or config area if the app needs user-linked services.",
        ),
        (
            "api-hardening",
            "API completeness & errors",
            "Ensure all CRUD routes exist with Pydantic validation, 404/422 handling, pagination "
            "or filtering on list endpoints, and pytest coverage for happy + error paths.",
        ),
    ],
    2: [
        (
            "search-filter-sort",
            "Search, filter & sort",
            "Add client-side or server-side search, filters, and sort controls on main lists. "
            "Include empty results messaging and preserve state in the URL where sensible.",
        ),
        (
            "forms-ux",
            "Form UX & validation",
            "Polish every form: inline validation, field-level errors, disabled submit while saving, "
            "success toasts/messages, and keyboard-friendly tab order.",
        ),
        (
            "responsive-mobile",
            "Responsive & mobile layout",
            "Make all primary screens usable on phone widths: stacked layouts, tap targets, "
            "collapsible nav, and readable typography.",
        ),
        (
            "empty-loading",
            "Empty, loading & error states",
            "Add skeleton/loading indicators, helpful empty states with CTAs, and retry UI for failed fetches.",
        ),
    ],
    3: [
        (
            "power-features",
            "Power-user features",
            "Add 2–3 high-value capabilities from requirements (e.g. bulk actions, export, favorites, "
            "recent history, detail panels, or keyboard shortcuts) — not cosmetic tweaks.",
        ),
        (
            "settings-config",
            "Settings & configuration UI",
            "If the app connects to external services, add a settings screen to configure URLs/keys "
            "(reading from env at runtime) with connection test and clear status.",
        ),
        (
            "data-persistence",
            "Data persistence & sync",
            "Ensure user data persists correctly across reloads; add optimistic updates or refresh "
            "after mutations where appropriate.",
        ),
    ],
    4: [
        (
            "onboarding-help",
            "Onboarding & help",
            "Add first-run hints, inline help text, or a short getting-started panel so new users "
            "understand the app without reading code.",
        ),
        (
            "accessibility-a11y",
            "Accessibility & quality",
            "Improve labels/ARIA on controls, focus management, color contrast, and semantic HTML.",
        ),
        (
            "edge-cases",
            "Edge cases & resilience",
            "Handle offline/slow API, large lists, invalid IDs, and concurrent edits gracefully.",
        ),
    ],
}


def classify_scope(
    title: str,
    description: str,
    notes: list[dict] | None = None,
    *,
    intake: dict | None = None,
) -> str:
    """Return in_scope, uncertain, or out_of_scope."""
    from app.services.intake_contract import (
        feature_matches_intake,
        intake_capability_lines,
        intake_explicitly_excludes,
    )

    text = f"{title} {description}".lower()
    notes = notes or []

    if feature_matches_intake(title, description, intake):
        return "in_scope"
    if intake_explicitly_excludes(title, description, intake):
        return "out_of_scope"

    for note in notes:
        if note.get("type") == "scope_out":
            scope_text = (note.get("content") or "").lower()
            if scope_text and scope_text in text:
                return "out_of_scope"

    uncertain_kws = [kw for kw in _SCOPE_UNCERTAIN_KEYWORDS if kw in text]
    if uncertain_kws:
        intake_blob = " ".join(intake_capability_lines(intake)).lower()
        if intake_blob and any(kw in intake_blob for kw in uncertain_kws):
            return "in_scope"
        return "uncertain"
    return "in_scope"


def resolve_feature_scope(
    title: str,
    description: str,
    notes: list[dict] | None = None,
    *,
    intake: dict | None = None,
    declared_scope: str | None = None,
) -> str:
    """Final scope for an enrichment feature — intake commitments override heuristics."""
    from app.services.intake_contract import feature_matches_intake, intake_explicitly_excludes

    if feature_matches_intake(title, description, intake):
        return "in_scope"
    if intake_explicitly_excludes(title, description, intake):
        return "out_of_scope"
    if declared_scope == "in_scope":
        return "in_scope"
    if declared_scope == "out_of_scope":
        return "out_of_scope"
    return classify_scope(title, description, notes, intake=intake)


def parse_enrichment_plan(raw: str | None) -> dict[str, Any]:
    """Schema-validated parse of an enrichment plan (see app/artifacts/schemas.py)."""
    from app.artifacts.parsing import parse_agent_json
    from app.artifacts.schemas import EnrichmentPlan

    if not raw:
        return {"features": [], "quality_issues": [], "stop_reason": "empty plan"}
    plan = parse_agent_json(EnrichmentPlan, raw)
    if plan is not None:
        return {
            "features": [f.model_dump() for f in plan.features],
            "quality_issues": plan.quality_issues,
            "stop_reason": plan.stop_reason,
        }
    return {"features": [], "quality_issues": [raw.strip()[:500]], "stop_reason": None}


def _human_approved_uncertain(title: str, input_responses: list[dict] | None) -> bool:
    for resp in input_responses or []:
        question = resp.get("question") or ""
        decision = (resp.get("resolved_decision") or resp.get("human_response") or "").lower()
        if title.lower() in question.lower() and decision.startswith("yes"):
            return True
    return False


def _expand_feature_description(title: str, description: str) -> str:
    """Ensure developers get actionable, substantial scope — not one-line tweaks."""
    desc = description.strip()
    if len(desc) >= 120 and "deliverable" in desc.lower():
        return desc
    return (
        f"{desc}\n\n"
        f"Deliverables for **{title}**:\n"
        "- Backend: routes/models/validation + pytest cases\n"
        "- Frontend: UI wired with loading, errors, and empty states\n"
        "- Verify through the factory live preview — ship a visible, testable improvement"
    )


def _batch_feature_dicts(features: list[dict], batch_size: int) -> list[list[dict]]:
    if not features:
        return []
    if len(features) <= batch_size:
        return [features]
    batches: list[list[dict]] = []
    for index in range(0, len(features), batch_size):
        batches.append(features[index : index + batch_size])
    return batches


def _batch_to_work_unit(batch: list[dict], batch_index: int) -> WorkUnit:
    lines = [
        "Implement **all** of the following improvements in this pass — substantial changes, not nits:",
        "",
    ]
    titles: list[str] = []
    for idx, item in enumerate(batch, start=1):
        title = str(item.get("title") or item.get("id") or f"Improvement {idx}").strip()
        description = str(item.get("description") or title).strip()
        titles.append(title)
        expanded = _expand_feature_description(title, description)
        lines.append(f"### {idx}. {title}")
        lines.append(expanded)
        lines.append("")

    slug_base = _slugify("-".join(t[:20] for t in titles[:3])) if titles else "batch"
    if len(titles) > 1:
        title_label = f"Enrichment batch {batch_index + 1}: {titles[0][:32]} + {len(titles) - 1} more"
        feature_id = f"enrichment-batch-{batch_index}-{_slugify(slug_base)[:20]}"
    else:
        title_label = f"Enhancement: {titles[0][:48]}"
        feature_id = _slugify(str(batch[0].get("id") or titles[0]))

    content = "\n".join(lines).strip()
    return WorkUnit(
        stream="feature",
        title=title_label,
        description=content,
        feature_id=feature_id[:48],
        feature_content=content,
    )


def features_to_work_units(
    features: list[dict],
    notes: list[dict] | None = None,
    input_responses: list[dict] | None = None,
    *,
    completed_slugs: set[str] | None = None,
    intake: dict | None = None,
) -> list[WorkUnit]:
    notes = notes or []
    completed_slugs = completed_slugs or set()
    in_scope: list[dict] = []
    seen: set[str] = set()

    for item in features:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("id") or "Improvement").strip()
        description = str(item.get("description") or title).strip()
        scope = resolve_feature_scope(
            title,
            description,
            notes,
            intake=intake,
            declared_scope=item.get("scope"),
        )
        if scope == "uncertain" and _human_approved_uncertain(title, input_responses):
            scope = "in_scope"
        if scope in ("out_of_scope", "uncertain") or not description:
            continue
        slug = _slugify(str(item.get("id") or title))
        if slug in seen or slug in completed_slugs:
            continue
        seen.add(slug)
        in_scope.append({**item, "title": title, "description": description, "id": slug})
        if len(in_scope) >= settings.max_features_per_enrichment_pass:
            break

    batch_size = max(2, settings.enrichment_features_per_agent)
    batches = _batch_feature_dicts(in_scope, batch_size)
    return [_batch_to_work_unit(batch, index) for index, batch in enumerate(batches)]


def local_enrichment_plan(
    audit: dict,
    pass_number: int,
    notes: list[dict] | None = None,
    *,
    max_passes: int | None = None,
    completed_slugs: set[str] | None = None,
    intake: dict | None = None,
) -> dict:
    """Deterministic fallback when Cursor architect is unavailable."""
    notes = notes or []
    completed_slugs = completed_slugs or set()
    cap = max_passes if max_passes is not None else settings.max_enrichment_passes
    if pass_number >= cap:
        return {"features": [], "quality_issues": [], "stop_reason": "max passes"}

    theme = _ENRICHMENT_PASS_THEMES.get(pass_number) or _ENRICHMENT_PASS_THEMES.get(
        ((pass_number - 1) % max(_ENRICHMENT_PASS_THEMES)) + 1, []
    )
    features: list[dict] = []

    for fid, title, desc in theme:
        if fid in completed_slugs:
            continue
        features.append(
            {"id": fid, "title": title, "description": desc, "scope": "in_scope", "priority": "high"}
        )

    endpoints = audit.get("endpoints") or []
    if not audit.get("has_html_ui") and "web-ui" not in completed_slugs:
        features.insert(
            0,
            {
                "id": "web-ui",
                "title": "Full web UI",
                "description": (
                    "Build a complete browser UI for the primary user journeys — not a placeholder page. "
                    "Include navigation, forms, lists, and API integration with relative fetch URLs."
                ),
                "scope": "in_scope",
                "priority": "high",
            },
        )
    elif not any("/api/" in e.get("path", "") for e in endpoints if e.get("ok")):
        features.insert(
            0,
            {
                "id": "core-api",
                "title": "Core API surface",
                "description": (
                    "Implement the full REST API the UI needs: list/create/read/update/delete, "
                    "validation, and tests. Expose OpenAPI-friendly routes under /api/."
                ),
                "scope": "in_scope",
                "priority": "high",
            },
        )

    for issue in audit.get("issues") or []:
        features.append(
            {
                "id": _slugify(str(issue)[:40]),
                "title": f"Fix: {str(issue)[:60]}",
                "description": f"Resolve audit issue: {issue}. Include tests where applicable.",
                "scope": "in_scope",
                "priority": "high",
            }
        )

    for note in notes:
        if note.get("type") not in ("feature", "instruction"):
            continue
        content = str(note.get("content") or "").strip()
        if len(content) < 12:
            continue
        for line in content.splitlines():
            line = line.strip(" •-\t")
            if len(line) < 12:
                continue
            slug = _slugify(line[:48])
            if slug in completed_slugs:
                continue
            features.append(
                {
                    "id": slug,
                    "title": line[:72],
                    "description": (
                        f"Deliver intake capability end-to-end (API + UI + tests): {line}"
                    ),
                    "scope": "in_scope",
                    "priority": "high",
                }
            )
            if len(features) >= settings.max_features_per_enrichment_pass:
                break

    filtered: list[dict] = []
    for feat in features[: settings.max_features_per_enrichment_pass]:
        scope = resolve_feature_scope(
            feat["title"],
            feat["description"],
            notes,
            intake=intake,
            declared_scope=feat.get("scope"),
        )
        feat["scope"] = scope
        slug = feat.get("id") or _slugify(feat["title"])
        if scope != "out_of_scope" and slug not in completed_slugs:
            filtered.append(feat)

    return {
        "features": filtered,
        "quality_issues": audit.get("issues") or [],
        "stop_reason": None if filtered else "no improvements identified",
    }


def enrichment_pass_theme_hint(pass_number: int) -> str:
    """Short architect guidance for what this pass should focus on."""
    theme = _ENRICHMENT_PASS_THEMES.get(pass_number) or _ENRICHMENT_PASS_THEMES.get(
        ((pass_number - 1) % max(_ENRICHMENT_PASS_THEMES)) + 1, []
    )
    if not theme:
        return "Ship substantial, user-visible improvements across backend and frontend."
    lines = [f"Pass {pass_number} focus areas (each should be a real milestone, not a nit):"]
    for _fid, title, desc in theme:
        lines.append(f"- **{title}**: {desc[:160]}{'…' if len(desc) > 160 else ''}")
    return "\n".join(lines)


def enrichment_change_summary(units: list[WorkUnit]) -> list[str]:
    """Human-readable list of what an enrichment pass will implement."""
    summaries: list[str] = []
    for unit in units:
        summaries.append(unit.title)
        if unit.feature_content:
            for line in unit.feature_content.splitlines():
                if line.startswith("### "):
                    summaries.append(line.replace("### ", "• "))
    return summaries


async def audit_live_preview(context: dict) -> dict:
    """Probe the running preview like a user would — HTTP only, no browser automation."""
    upstream = context.get("preview_upstream") or context.get("preview_url") or ""
    health_path = context.get("preview_health_path") or "/health"
    if not str(health_path).startswith("/"):
        health_path = f"/{health_path}"

    audit: dict[str, Any] = {
        "upstream": upstream,
        "endpoints": [],
        "issues": [],
        "has_html_ui": False,
        "health_ok": False,
        "mobile_friendly": False,
        "viewport_meta": False,
        "responsive_signals": [],
    }
    if not upstream:
        audit["issues"].append("Live preview is not running")
        return audit

    base = upstream.rstrip("/")
    paths = [
        ("GET", health_path),
        ("GET", "/api/info"),
        ("GET", "/api/items"),
        ("GET", "/"),
        ("GET", "/index.html"),
    ]

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            for method, path in paths:
                if not path.startswith("/"):
                    path = f"/{path}"
                url = f"{base}{path}"
                entry = {"method": method, "path": path, "url": url, "status": None, "ok": False}
                try:
                    response = await client.request(method, url)
                    entry["status"] = response.status_code
                    entry["ok"] = 200 <= response.status_code < 400
                    content_type = response.headers.get("content-type", "")
                    if "text/html" in content_type and entry["ok"]:
                        audit["has_html_ui"] = True
                        body = response.text[:50_000]
                        body_lower = body.lower()
                        if 'name="viewport"' in body_lower or "viewport" in body_lower:
                            audit["viewport_meta"] = True
                        responsive_markers = (
                            "@media",
                            "max-width",
                            "min-width",
                            "mobile",
                            "responsive",
                            "flex-wrap",
                            "grid-template",
                        )
                        found = [m for m in responsive_markers if m in body_lower]
                        if found:
                            audit["responsive_signals"] = found[:6]
                        audit["mobile_friendly"] = audit["viewport_meta"] or len(found) >= 2
                    if path == health_path and entry["ok"]:
                        audit["health_ok"] = True
                except httpx.HTTPError as exc:
                    entry["error"] = str(exc)[:200]
                    audit["issues"].append(f"{method} {path} failed: {exc}")
                audit["endpoints"].append(entry)

            if not audit["health_ok"]:
                audit["issues"].append("Health endpoint is not returning success")
            if not audit["has_html_ui"]:
                audit["issues"].append("No HTML UI detected at / or /index.html")
            if audit["has_html_ui"] and not audit["mobile_friendly"]:
                audit["issues"].append(
                    "UI may not be mobile-friendly — add viewport meta and responsive layout"
                )
    except Exception as exc:
        audit["issues"].append(f"Preview audit error: {exc}")

    return audit
