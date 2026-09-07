import json
from uuid import uuid4

import pytest

from app.artifacts.schemas import CycleImprovementSuggestion, UserPerspectiveReviewReport
from app.services.user_perspective_review import (
    load_all_improvement_backlog_items,
    merge_cycle_improvement_backlog,
    persist_user_perspective_review,
    run_local_user_perspective_review,
)
from app.workspace.manager import WorkspaceManager


@pytest.mark.asyncio
async def test_local_user_perspective_review_suggests_improvements(monkeypatch, tmp_path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    monkeypatch.setattr("app.config.settings.workspace_root", str(ws_root))
    ws = WorkspaceManager()
    project_id = uuid4()

    report = await run_local_user_perspective_review(
        ws,
        project_id,
        {
            "preview_upstream": "http://preview:8080",
            "preview_audit": {
                "health_ok": True,
                "has_html_ui": True,
                "mobile_friendly": False,
                "issues": ["List page returns empty without explanation"],
                "endpoints": [{"path": "/api/items", "ok": True}],
            },
            "user_journey_report": {
                "ux_improvements": [
                    {
                        "title": "Add empty state CTA",
                        "description": "Show a button when no items exist",
                        "severity": "medium",
                    }
                ]
            },
            "intake": {"must_have_features": "- Search items\n- Export CSV"},
        },
    )
    assert report.passed is True
    assert len(report.suggestions) >= 3
    titles = " ".join(s.title.lower() for s in report.suggestions)
    assert "mobile" in titles or "empty" in titles or "search" in titles


def test_merge_cycle_improvement_backlog_dedupes():
    existing = json.dumps(
        {
            "items": [
                {
                    "title": "Dark mode",
                    "description": "Add theme toggle",
                    "source": "user_perspective_review",
                }
            ]
        }
    )
    merged = merge_cycle_improvement_backlog(
        existing,
        [
            CycleImprovementSuggestion(title="Dark mode", description="dup", category="ui"),
            CycleImprovementSuggestion(
                title="Fix broken nav",
                description="Settings link 404s",
                category="bug_fix",
                priority="high",
            ),
        ],
        cycle_number=2,
    )
    assert len(merged["items"]) == 2
    assert merged["items"][-1]["category"] == "bug_fix"
    assert merged["items"][-1]["cycle_number"] == 2


@pytest.mark.asyncio
async def test_persist_and_load_improvement_backlog(monkeypatch, tmp_path):
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    monkeypatch.setattr("app.config.settings.workspace_root", str(ws_root))
    ws = WorkspaceManager()
    project_id = uuid4()

    report = UserPerspectiveReviewReport(
        passed=True,
        summary="Looks okay but needs polish",
        suggestions=[
            CycleImprovementSuggestion(
                title="Add bulk delete",
                description="Let users delete multiple items at once",
                category="feature",
                priority="high",
            )
        ],
    )
    await persist_user_perspective_review(ws, project_id, report, cycle_number=1)
    assert "user-perspective-review.json" in ws.list_artifacts(project_id)
    assert "cycle-improvement-backlog.json" in ws.list_artifacts(project_id)

    items = load_all_improvement_backlog_items(ws, project_id)
    assert any("bulk delete" in item.get("title", "").lower() for item in items)
