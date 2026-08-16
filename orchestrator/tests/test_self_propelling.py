from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.self_propelling import (
    audit_fingerprint,
    get_self_propelling_settings,
    is_due_for_post_production,
    is_self_propelling_enabled,
    resolve_post_production_passes,
    save_self_propelling_settings,
    should_skip_architect,
)
from app.workspace.manager import WorkspaceManager


def test_audit_fingerprint_stable():
    audit = {
        "health_ok": True,
        "has_html_ui": True,
        "mobile_friendly": True,
        "issues": ["a"],
        "endpoints": [{"path": "/health", "ok": True}],
    }
    assert audit_fingerprint(audit) == audit_fingerprint(audit)


def test_should_skip_architect_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(WorkspaceManager, "__init__", lambda self: None)
    ws = WorkspaceManager()
    project_id = uuid4()
    ws.load_metadata = MagicMock(
        return_value={"self_propelling": {"last_audit_fingerprint": audit_fingerprint({"health_ok": True, "issues": [], "endpoints": []})}}
    )
    audit = {"health_ok": True, "issues": [], "endpoints": []}
    assert should_skip_architect(project_id, audit, ws) is True


def test_self_propelling_settings_roundtrip(tmp_path, monkeypatch):
    meta_store: dict = {}

    def load_metadata(_pid):
        return dict(meta_store)

    def save_metadata(_pid, meta):
        meta_store.clear()
        meta_store.update(meta)

    monkeypatch.setattr(WorkspaceManager, "__init__", lambda self: None)
    ws = WorkspaceManager()
    ws.load_metadata = load_metadata
    ws.save_metadata = save_metadata

    project_id = uuid4()
    save_self_propelling_settings(
        project_id,
        enabled=True,
        post_production_passes=3,
        interval_hours=12,
        token_budget_per_cycle=100_000,
        workspace=ws,
    )
    settings = get_self_propelling_settings(project_id, ws)
    assert settings["enabled"] is True
    assert settings["post_production_passes"] == 3
    assert is_self_propelling_enabled(project_id, ws)
    assert resolve_post_production_passes(project_id, ws) == 3


def test_is_due_when_no_next_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(WorkspaceManager, "__init__", lambda self: None)
    ws = WorkspaceManager()
    project_id = uuid4()
    ws.load_metadata = MagicMock(
        return_value={"self_propelling": {"enabled": True}}
    )
    assert is_due_for_post_production(project_id, ws) is True


@pytest.mark.asyncio
async def test_maybe_schedule_post_production_requires_production():
    from app.services.self_propelling import maybe_schedule_post_production

    project_id = uuid4()
    session = AsyncMock()
    row = MagicMock()
    row.state = "REVIEW"
    session.get.return_value = row

    assert await maybe_schedule_post_production(session, project_id) is False


@pytest.mark.asyncio
async def test_feedback_pipeline_at_production_with_self_propelling():
    from app.services.feedback_pipeline import maybe_schedule_feedback_pipeline

    project_id = uuid4()
    session = AsyncMock()
    row = MagicMock()
    row.state = "PRODUCTION"
    session.get.return_value = row

    with patch("app.services.self_propelling.is_self_propelling_enabled", return_value=True), patch(
        "app.services.self_propelling.maybe_schedule_post_production", new_callable=AsyncMock, return_value=True
    ) as schedule:
        assert await maybe_schedule_feedback_pipeline(session, project_id) is True
        schedule.assert_awaited_once()
