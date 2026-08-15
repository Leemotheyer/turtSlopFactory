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

_IN_SCOPE_QUALITY_FEATURES = [
    (
        "input-validation",
        "Input validation & errors",
        "Add validation on all user inputs with clear error messages and HTTP 422 responses.",
    ),
    (
        "empty-states",
        "Empty & loading states",
        "Add loading indicators, empty-state copy, and disabled buttons while requests are in flight.",
    ),
    (
        "responsive-ui",
        "Responsive layout",
        "Make the UI usable on mobile widths with sensible spacing and tap targets.",
    ),
    (
        "delete-flow",
        "Complete CRUD",
        "Ensure list/create/update/delete flows exist where appropriate, with confirmation for destructive actions.",
    ),
]


def classify_scope(title: str, description: str, notes: list[dict] | None = None) -> str:
    """Return in_scope, uncertain, or out_of_scope."""
    text = f"{title} {description}".lower()
    notes = notes or []
    for note in notes:
        if note.get("type") == "scope_out":
            scope_text = (note.get("content") or "").lower()
            if scope_text and scope_text in text:
                return "out_of_scope"
    if any(kw in text for kw in _SCOPE_UNCERTAIN_KEYWORDS):
        return "uncertain"
    return "in_scope"


def parse_enrichment_plan(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"features": [], "quality_issues": [], "stop_reason": "empty plan"}
    text = raw.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {
                    "features": data.get("features") or [],
                    "quality_issues": data.get("quality_issues") or [],
                    "stop_reason": data.get("stop_reason"),
                }
        except json.JSONDecodeError:
            pass
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return {
                    "features": data.get("features") or [],
                    "quality_issues": data.get("quality_issues") or [],
                    "stop_reason": data.get("stop_reason"),
                }
        except json.JSONDecodeError:
            pass
    return {"features": [], "quality_issues": [text[:500]], "stop_reason": None}


def _human_approved_uncertain(title: str, input_responses: list[dict] | None) -> bool:
    for resp in input_responses or []:
        question = resp.get("question") or ""
        decision = (resp.get("resolved_decision") or resp.get("human_response") or "").lower()
        if title.lower() in question.lower() and decision.startswith("yes"):
            return True
    return False


def features_to_work_units(
    features: list[dict],
    notes: list[dict] | None = None,
    input_responses: list[dict] | None = None,
) -> list[WorkUnit]:
    notes = notes or []
    units: list[WorkUnit] = []
    seen: set[str] = set()
    for item in features:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("id") or "Improvement").strip()
        description = str(item.get("description") or title).strip()
        scope = item.get("scope") or classify_scope(title, description, notes)
        if scope == "uncertain" and _human_approved_uncertain(title, input_responses):
            scope = "in_scope"
        if scope == "out_of_scope" or scope == "uncertain":
            continue
        if not description:
            continue
        slug = _slugify(str(item.get("id") or title))
        if slug in seen:
            slug = f"{slug}-{len(seen)}"
        seen.add(slug)
        units.append(
            WorkUnit(
                stream="feature",
                title=f"Enhancement: {title[:48]}",
                description=description,
                feature_id=slug,
                feature_content=description,
            )
        )
        if len(units) >= settings.max_features_per_enrichment_pass:
            break
    return units


def local_enrichment_plan(
    audit: dict, pass_number: int, notes: list[dict] | None = None, max_passes: int | None = None
) -> dict:
    """Deterministic fallback when Cursor architect is unavailable."""
    notes = notes or []
    features: list[dict] = []
    endpoints = audit.get("endpoints") or []
    has_ui = audit.get("has_html_ui", False)

    if not any("/api/items" in e.get("path", "") for e in endpoints if e.get("method") == "GET"):
        features.append(
            {
                "id": "items-api",
                "title": "Item API",
                "description": "Expose list/create/get/update/delete endpoints for the core resource.",
                "scope": "in_scope",
                "priority": "high",
            }
        )

    if has_ui:
        for fid, title, desc in _IN_SCOPE_QUALITY_FEATURES:
            features.append(
                {"id": fid, "title": title, "description": desc, "scope": "in_scope", "priority": "medium"}
            )
    else:
        features.append(
            {
                "id": "web-ui",
                "title": "Web UI",
                "description": "Add a browser UI that exercises the API with forms and lists.",
                "scope": "in_scope",
                "priority": "high",
            }
        )

    if pass_number >= (max_passes if max_passes is not None else settings.max_enrichment_passes):
        return {"features": [], "quality_issues": [], "stop_reason": "max passes"}

    # Drop features that duplicate scope_out notes
    filtered = []
    for feat in features[: settings.max_features_per_enrichment_pass]:
        scope = classify_scope(feat["title"], feat["description"], notes)
        feat["scope"] = scope
        if scope != "out_of_scope":
            filtered.append(feat)

    return {
        "features": filtered,
        "quality_issues": audit.get("issues") or [],
        "stop_reason": None if filtered else "no improvements identified",
    }


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
    except Exception as exc:
        audit["issues"].append(f"Preview audit error: {exc}")

    return audit
