"""Tests for per-project pipeline settings and first-build change-budget exemption."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.project_settings import (
    apply_project_settings_to_context,
    project_settings_payload,
    resolve_change_budget_files,
    resolve_change_budget_lines,
    should_enforce_change_budget,
)


def _project(**kwargs):
    defaults = {
        "change_budget_files": None,
        "change_budget_lines": None,
        "max_fix_attempts": None,
        "adversary_enabled": None,
        "enforce_change_budget": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_resolve_change_budget_uses_project_override():
    project = _project(change_budget_files=25, change_budget_lines=2000)
    assert resolve_change_budget_files(project) == 25
    assert resolve_change_budget_lines(project) == 2000


def test_should_enforce_change_budget_first_build_exempt_by_default():
    project = _project()
    assert should_enforce_change_budget(project, review_ever_approved=False) is False
    assert should_enforce_change_budget(project, review_ever_approved=True) is True


def test_should_enforce_change_budget_project_override():
    project = _project(enforce_change_budget=True)
    assert should_enforce_change_budget(project, review_ever_approved=False) is True
    project = _project(enforce_change_budget=False)
    assert should_enforce_change_budget(project, review_ever_approved=True) is False


def test_apply_project_settings_to_context_first_build():
    project = _project()
    context: dict = {}
    apply_project_settings_to_context(project, context)
    assert context["change_budget_enforced"] is False
    assert context["effective_change_budget_files"] >= 1


def test_project_settings_payload_includes_factory_defaults():
    payload = project_settings_payload(_project(), review_ever_approved=False)
    assert "factory_defaults" in payload
    assert payload["change_budget_enforced"] is False


@pytest.mark.asyncio
async def test_reviewer_skips_change_budget_on_first_build(tmp_path):
    from app.agents.local_runner import LocalAgentRunner

    runner = LocalAgentRunner(MagicMock())
    project_id = uuid4()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Dockerfile").write_text("FROM python:3.12")
    runner.workspace.list_artifacts = MagicMock(return_value=["acceptance-report.json"])
    runner.workspace.read_artifact = MagicMock(
        return_value='{"all_verified": true, "requirements": {}}'
    )
    runner.workspace.repo_dir = MagicMock(return_value=repo)
    runner.workspace.write_artifact = MagicMock()
    runner.workspace.append_log = MagicMock()

    context = {
        "tests_passed": True,
        "acceptance_report": {"all_verified": True, "requirements": {}},
        "change_stats_oversized": True,
        "change_budget_enforced": False,
        "notes": [],
    }
    ok, _ = await runner._reviewer(project_id, context, uuid4(), "local-reviewer")
    assert ok is True


@pytest.mark.asyncio
async def test_reviewer_rejects_oversized_change_when_budget_enforced(tmp_path):
    from app.agents.local_runner import LocalAgentRunner

    runner = LocalAgentRunner(MagicMock())
    project_id = uuid4()
    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "Dockerfile").write_text("FROM python:3.12")
    runner.workspace.list_artifacts = MagicMock(return_value=["acceptance-report.json"])
    runner.workspace.read_artifact = MagicMock(
        return_value='{"all_verified": true, "requirements": {}}'
    )
    runner.workspace.repo_dir = MagicMock(return_value=repo)
    runner.workspace.write_artifact = MagicMock()
    runner.workspace.append_log = MagicMock()

    context = {
        "tests_passed": True,
        "acceptance_report": {"all_verified": True, "requirements": {}},
        "change_stats_oversized": True,
        "change_budget_enforced": True,
        "notes": [],
    }
    ok, _ = await runner._reviewer(project_id, context, uuid4(), "local-reviewer")
    assert ok is False


@pytest.mark.asyncio
async def test_record_change_stats_skips_oversized_on_first_build():
    from app.services.change_stats import record_change_stats

    ex = MagicMock()
    ex.workspace.repo_dir.return_value = MagicMock()
    session = AsyncMock()
    project = SimpleNamespace(id=uuid4())

    with patch("app.services.change_stats.compute_change_stats", return_value={
        "files_changed": 40,
        "lines_changed": 3000,
        "method": "git",
    }), patch("app.services.evidence.record_evidence", new_callable=AsyncMock) as record:
        context = {"change_budget_enforced": False, "effective_change_budget_files": 8, "effective_change_budget_lines": 500}
        stats = await record_change_stats(
            ex, session, project, {}, label="test", context=context, outputs=""
        )
        assert stats["oversized"] is False
        record.assert_awaited_once()
        assert record.await_args.kwargs["passed"] is True
