"""Simulate a human user exercising the live staging preview before production.

Uses HTTP + HTML inspection against the internal preview URL (no browser automation
required). Blocking failures feed the fix loop; UX improvements are stored for
future enrichment passes without blocking review.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

import httpx

from app.artifacts.schemas import UserJourneyFinding, UserJourneyReport, UserJourneyStep
from app.services.intake_contract import intake_capability_lines

_FORM_TAG_RE = re.compile(r"<form\b", re.I)
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
_BUTTON_RE = re.compile(r"<button\b", re.I)
_LINK_RE = re.compile(r"""<a\b[^>]*href=["']([^"'#][^"']*)["']""", re.I)
_SEARCH_RE = re.compile(r"""<input\b[^>]*(search|query|q)=["'][^"']*["']""", re.I)


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.forms = 0
        self.buttons = 0
        self.inputs = 0
        self.has_search_input = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag_lower == "a" and attr_map.get("href"):
            self.links.append(attr_map["href"])
        elif tag_lower == "form":
            self.forms += 1
        elif tag_lower == "button":
            self.buttons += 1
        elif tag_lower == "input":
            self.inputs += 1
            input_type = attr_map.get("type", "text").lower()
            name = (attr_map.get("name") or attr_map.get("id") or "").lower()
            if input_type == "search" or "search" in name or name in {"q", "query"}:
                self.has_search_input = True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _analyze_html(html: str) -> dict[str, Any]:
    collector = _LinkCollector()
    try:
        collector.feed(html[:200_000])
    except Exception:
        pass
    return {
        "links": collector.links[:40],
        "forms": collector.forms,
        "buttons": collector.buttons,
        "inputs": collector.inputs,
        "has_search_input": collector.has_search_input or bool(_SEARCH_RE.search(html[:50_000])),
        "interactive": collector.forms + collector.buttons + collector.inputs > 0,
    }


def _intake_journey_expectations(intake: dict | None) -> list[str]:
    lines = intake_capability_lines(intake)
    expectations: list[str] = []
    blob = " ".join(lines).lower()
    mapping = (
        ("search", "User can search or filter the catalog"),
        ("download", "User can download or fetch content"),
        ("library", "User can browse a library or collection view"),
        ("catalog", "User can browse a catalog listing"),
        ("track", "User can track items or progress"),
        ("manage", "User can manage items (create/edit/delete)"),
        ("queue", "User can view or manage a queue"),
        ("import", "User can import or add new items"),
        ("sync", "User can sync or refresh data"),
        ("index", "User can index or discover content"),
    )
    for keyword, label in mapping:
        if keyword in blob:
            expectations.append(label)
    if not expectations and lines:
        expectations.append(f"Core intake flow works: {lines[0][:120]}")
    return expectations[:8]


async def run_user_journey_tests(context: dict) -> UserJourneyReport:
    """Exercise the staging preview like a user would; return structured findings."""
    upstream = (context.get("preview_upstream") or "").rstrip("/")
    intake = context.get("intake") or {}
    steps: list[UserJourneyStep] = []
    blocking: list[UserJourneyFinding] = []
    ux: list[UserJourneyFinding] = []

    if not upstream:
        blocking.append(
            UserJourneyFinding(
                severity="high",
                category="blocking",
                title="Preview unavailable",
                description="No live staging preview to exercise — user journey testing cannot run",
            )
        )
        return UserJourneyReport(
            passed=False,
            steps=steps,
            blocking_findings=blocking,
            ux_improvements=ux,
            notes="Preview URL missing",
        )

    base = upstream
    expectations = _intake_journey_expectations(intake)
    api_works = False
    ui_works = False

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # Step 1: open the app like a user landing on the home page
        home_html = ""
        try:
            response = await client.get(f"{base}/")
            home_ok = 200 <= response.status_code < 400
            content_type = response.headers.get("content-type", "")
            if "text/html" in content_type and home_ok:
                home_html = response.text[:200_000]
                ui_works = True
            steps.append(
                UserJourneyStep(
                    action="Open home page",
                    target="/",
                    success=home_ok,
                    detail=f"HTTP {response.status_code}",
                )
            )
            if not home_ok:
                blocking.append(
                    UserJourneyFinding(
                        severity="high",
                        category="blocking",
                        title="Home page unreachable",
                        description=f"GET / returned HTTP {response.status_code} — users cannot open the app",
                    )
                )
        except httpx.HTTPError as exc:
            steps.append(UserJourneyStep(action="Open home page", target="/", success=False, detail=str(exc)[:200]))
            blocking.append(
                UserJourneyFinding(
                    severity="high",
                    category="blocking",
                    title="Home page failed to load",
                    description=str(exc)[:300],
                )
            )

        html_info = _analyze_html(home_html) if home_html else {}
        if ui_works and not html_info.get("interactive"):
            ux.append(
                UserJourneyFinding(
                    severity="medium",
                    category="ux_improvement",
                    title="No obvious interactive controls",
                    description=(
                        "The home page loads but has no forms, buttons, or inputs — "
                        "users may not know how to start"
                    ),
                )
            )

        # Step 2: follow primary navigation links (in-app only)
        visited = {"/"}
        for href in html_info.get("links") or []:
            if len(visited) >= 4:
                break
            if href.startswith(("http://", "https://", "mailto:", "javascript:")):
                continue
            path = href if href.startswith("/") else f"/{href}"
            if path in visited or path.startswith("/api/"):
                continue
            visited.add(path)
            try:
                nav_resp = await client.get(f"{base}{path}")
                nav_ok = 200 <= nav_resp.status_code < 400
                steps.append(
                    UserJourneyStep(
                        action="Follow navigation link",
                        target=path,
                        success=nav_ok,
                        detail=f"HTTP {nav_resp.status_code}",
                    )
                )
                if not nav_ok:
                    ux.append(
                        UserJourneyFinding(
                            severity="medium",
                            category="ux_improvement",
                            title=f"Navigation link broken: {path}",
                            description=f"Link from home returned HTTP {nav_resp.status_code}",
                        )
                    )
            except httpx.HTTPError as exc:
                steps.append(
                    UserJourneyStep(
                        action="Follow navigation link",
                        target=path,
                        success=False,
                        detail=str(exc)[:200],
                    )
                )

        # Step 3: API list — browse catalog
        items_path = "/api/items"
        created_id: str | None = None
        try:
            list_resp = await client.get(f"{base}{items_path}")
            list_ok = 200 <= list_resp.status_code < 400
            api_works = list_ok
            steps.append(
                UserJourneyStep(
                    action="Browse catalog (list API)",
                    target=items_path,
                    success=list_ok,
                    detail=f"HTTP {list_resp.status_code}",
                )
            )
            if not list_ok and any("catalog" in e.lower() or "browse" in e.lower() for e in expectations):
                blocking.append(
                    UserJourneyFinding(
                        severity="high",
                        category="blocking",
                        title="Catalog list unavailable",
                        description=f"GET {items_path} returned HTTP {list_resp.status_code}",
                    )
                )
        except httpx.HTTPError as exc:
            steps.append(
                UserJourneyStep(
                    action="Browse catalog (list API)",
                    target=items_path,
                    success=False,
                    detail=str(exc)[:200],
                )
            )

        # Step 4: create an item (common user action)
        list_was_ok = api_works
        try:
            create_resp = await client.post(
                f"{base}{items_path}",
                json={"name": "Factory journey test item", "title": "Journey test"},
            )
            create_ok = 200 <= create_resp.status_code < 400
            if create_ok:
                api_works = True
                try:
                    body = create_resp.json()
                    created_id = str(body.get("id") or body.get("item_id") or "")
                except Exception:
                    created_id = None
            steps.append(
                UserJourneyStep(
                    action="Create item via API",
                    target=f"POST {items_path}",
                    success=create_ok,
                    detail=f"HTTP {create_resp.status_code}",
                )
            )
            if not create_ok and any("manage" in e.lower() for e in expectations):
                blocking.append(
                    UserJourneyFinding(
                        severity="high",
                        category="blocking",
                        title="Cannot create items",
                        description=(
                            f"POST {items_path} returned HTTP {create_resp.status_code} — "
                            "core create flow is broken"
                        ),
                    )
                )
            elif not create_ok and list_was_ok:
                ux.append(
                    UserJourneyFinding(
                        severity="low",
                        category="ux_improvement",
                        title="Create flow may be missing or strict",
                        description=f"POST {items_path} returned HTTP {create_resp.status_code}",
                    )
                )
        except httpx.HTTPError as exc:
            steps.append(
                UserJourneyStep(
                    action="Create item via API",
                    target=f"POST {items_path}",
                    success=False,
                    detail=str(exc)[:200],
                )
            )

        # Step 5: read back created item
        if created_id:
            detail_path = f"{items_path}/{created_id}"
            try:
                detail_resp = await client.get(f"{base}{detail_path}")
                detail_ok = 200 <= detail_resp.status_code < 400
                steps.append(
                    UserJourneyStep(
                        action="View item detail",
                        target=detail_path,
                        success=detail_ok,
                        detail=f"HTTP {detail_resp.status_code}",
                    )
                )
                if not detail_ok:
                    blocking.append(
                        UserJourneyFinding(
                            severity="high",
                            category="blocking",
                            title="Item detail view broken",
                            description=f"GET {detail_path} returned HTTP {detail_resp.status_code}",
                        )
                    )
            except httpx.HTTPError as exc:
                steps.append(
                    UserJourneyStep(
                        action="View item detail",
                        target=detail_path,
                        success=False,
                        detail=str(exc)[:200],
                    )
                )

        # Step 6: search (intake or UI signal)
        search_paths = ["/api/search", "/api/items/search", "/api/items?q=test"]
        wants_search = html_info.get("has_search_input") or any("search" in e.lower() for e in expectations)
        if wants_search:
            search_ok = False
            for path in search_paths:
                try:
                    if "?" in path:
                        search_resp = await client.get(f"{base}{path}")
                    else:
                        search_resp = await client.get(f"{base}{path}", params={"q": "test"})
                    if 200 <= search_resp.status_code < 400:
                        search_ok = True
                        steps.append(
                            UserJourneyStep(
                                action="Search catalog",
                                target=path,
                                success=True,
                                detail=f"HTTP {search_resp.status_code}",
                            )
                        )
                        break
                except httpx.HTTPError:
                    continue
            if not search_ok:
                steps.append(
                    UserJourneyStep(
                        action="Search catalog",
                        target="search endpoints",
                        success=False,
                        detail="No working search endpoint found",
                    )
                )
                if any("search" in e.lower() for e in expectations):
                    blocking.append(
                        UserJourneyFinding(
                            severity="high",
                            category="blocking",
                            title="Search does not work",
                            description=(
                                "Intake requires search but no /api/search or query endpoint responded successfully"
                            ),
                        )
                    )
                elif html_info.get("has_search_input"):
                    ux.append(
                        UserJourneyFinding(
                            severity="medium",
                            category="ux_improvement",
                            title="Search UI not wired to API",
                            description="Search input detected in HTML but no search API responded successfully",
                        )
                    )

        # Step 7: health (user expects app to feel alive)
        health_path = context.get("preview_health_path") or "/health"
        if not str(health_path).startswith("/"):
            health_path = f"/{health_path}"
        try:
            health_resp = await client.get(f"{base}{health_path}")
            health_ok = 200 <= health_resp.status_code < 400
            steps.append(
                UserJourneyStep(
                    action="Check app health",
                    target=health_path,
                    success=health_ok,
                    detail=f"HTTP {health_resp.status_code}",
                )
            )
            if not health_ok:
                blocking.append(
                    UserJourneyFinding(
                        severity="high",
                        category="blocking",
                        title="Health check failing",
                        description=f"GET {health_path} returned HTTP {health_resp.status_code}",
                    )
                )
        except httpx.HTTPError as exc:
            steps.append(
                UserJourneyStep(
                    action="Check app health",
                    target=health_path,
                    success=False,
                    detail=str(exc)[:200],
                )
            )

    # Intake expectations without evidence
    if expectations and not ui_works and not api_works:
        blocking.append(
            UserJourneyFinding(
                severity="high",
                category="blocking",
                title="Core product surface missing",
                description=(
                    "Neither a usable UI nor working API was detected, but intake requires: "
                    + "; ".join(expectations[:3])
                ),
            )
        )
    elif expectations and not ui_works:
        ux.append(
            UserJourneyFinding(
                severity="medium",
                category="ux_improvement",
                title="API-only — no browser UI detected",
                description="Intake implies a product UI but only API endpoints responded",
            )
        )

    passed = len(blocking) == 0 and any(s.success for s in steps)
    return UserJourneyReport(
        passed=passed,
        steps=steps,
        blocking_findings=blocking,
        ux_improvements=ux,
        intake_expectations=expectations,
        notes=f"Exercised {len(steps)} user step(s) against {base}",
    )


def merge_ux_improvement_backlog(
    existing_raw: str | None,
    new_items: list[UserJourneyFinding],
) -> dict[str, Any]:
    """Merge UX findings into a cumulative backlog for future enrichment."""
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
    for finding in new_items:
        title = finding.title.strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        backlog["items"].append(
            {
                "id": title.lower().replace(" ", "-")[:48],
                "title": title,
                "description": finding.description[:500],
                "severity": finding.severity,
                "source": "user_journey",
                "created_at": _utc_now(),
            }
        )
    backlog["items"] = backlog["items"][-50:]
    backlog["updated_at"] = _utc_now()
    return backlog


def format_blocking_failure(report: UserJourneyReport) -> str:
    lines = [
        "User journey testing found blocking issues — a real user could not complete core flows:",
        "",
    ]
    for finding in report.blocking_findings[:10]:
        lines.append(f"- [{finding.severity}] {finding.title}: {finding.description[:300]}")
    failed_steps = [s for s in report.steps if not s.success]
    if failed_steps:
        lines.append("")
        lines.append("Failed steps:")
        for step in failed_steps[:8]:
            lines.append(f"- {step.action} ({step.target}): {step.detail}")
    lines.append("")
    lines.append("Fix these issues so intake capabilities work end-to-end in the live preview.")
    return "\n".join(lines)


async def persist_user_journey_results(
    workspace,
    project_id: UUID,
    report: UserJourneyReport,
) -> None:
    workspace.write_artifact(
        project_id,
        "user-journey-report.json",
        report.model_dump_json(indent=2),
    )
    existing = None
    if "ux-improvement-backlog.json" in workspace.list_artifacts(project_id):
        existing = workspace.read_artifact(project_id, "ux-improvement-backlog.json")
    backlog = merge_ux_improvement_backlog(existing, report.ux_improvements)
    workspace.write_artifact(
        project_id,
        "ux-improvement-backlog.json",
        json.dumps(backlog, indent=2),
    )


def load_ux_backlog_items(workspace, project_id: UUID) -> list[dict[str, Any]]:
    """UX improvements from prior user-journey runs — for enrichment planning."""
    if "ux-improvement-backlog.json" not in workspace.list_artifacts(project_id):
        return []
    try:
        raw = workspace.read_artifact(project_id, "ux-improvement-backlog.json") or "{}"
        data = json.loads(raw)
        items = data.get("items") if isinstance(data, dict) else []
        return [item for item in items if isinstance(item, dict)]
    except (json.JSONDecodeError, TypeError):
        return []
