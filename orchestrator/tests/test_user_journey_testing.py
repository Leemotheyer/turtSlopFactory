"""Tests for simulated user journey testing before production."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.artifacts.schemas import UserJourneyFinding, UserJourneyReport
from app.services.user_journey_testing import (
    format_blocking_failure,
    merge_ux_improvement_backlog,
    run_user_journey_tests,
)


def _html_response(text: str):
    response = MagicMock()
    response.status_code = 200
    response.text = text
    response.headers = {"content-type": "text/html"}
    return response


def _json_response(payload=None, status_code: int = 200):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=payload or {})
    response.headers = {"content-type": "application/json"}
    return response


def _client(handler):
    client = AsyncMock()

    async def _request(method, url, **kwargs):
        return await handler(method, url, **kwargs)

    client.request = _request
    client.get = lambda url, **kwargs: _request("GET", url, **kwargs)
    client.post = lambda url, **kwargs: _request("POST", url, **kwargs)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    return client


@pytest.mark.asyncio
async def test_user_journey_fails_without_preview():
    report = await run_user_journey_tests({})
    assert report.passed is False
    assert report.blocking_findings
    assert report.blocking_findings[0].title == "Preview unavailable"


@pytest.mark.asyncio
async def test_user_journey_passes_healthy_ui_and_api():
    async def handler(method, url, **kwargs):
        if url.endswith("/api/items") and method == "GET":
            return _json_response([])
        if url.endswith("/api/items") and method == "POST":
            return _json_response({"id": 1})
        if url.endswith("/api/items/1"):
            return _json_response({"id": 1})
        if url.endswith("/health"):
            return _json_response({"status": "ok"})
        if url.endswith("/") and method == "GET":
            return _html_response("<html><body><button>Go</button><a href='/items'>Items</a></body></html>")
        if url.endswith("/items"):
            return _html_response("<html><body>Items</body></html>")
        response = MagicMock()
        response.status_code = 404
        return response

    with patch(
        "app.services.user_journey_testing.httpx.AsyncClient",
        return_value=_client(handler),
    ):
        report = await run_user_journey_tests(
            {"preview_upstream": "http://preview", "preview_health_path": "/health", "intake": {}}
        )
    assert report.passed is True
    assert not report.blocking_findings
    assert any(step.success for step in report.steps)


@pytest.mark.asyncio
async def test_user_journey_blocks_when_search_required_but_missing():
    async def handler(method, url, **kwargs):
        if url.endswith("/") and method == "GET":
            return _html_response("<html><body><input name='search'/></body></html>")
        if url.endswith("/api/items") and method == "GET":
            return _json_response([])
        if url.endswith("/api/items") and method == "POST":
            return _json_response({}, status_code=422)
        if "search" in url or "q=test" in url:
            return _json_response({}, status_code=404)
        if url.endswith("/health"):
            return _json_response({"status": "ok"})
        return _json_response({}, status_code=404)

    with patch(
        "app.services.user_journey_testing.httpx.AsyncClient",
        return_value=_client(handler),
    ):
        report = await run_user_journey_tests(
            {
                "preview_upstream": "http://preview",
                "preview_health_path": "/health",
                "intake": {"must_have_features": "Search manga catalog"},
            }
        )
    assert report.passed is False
    assert any("search" in f.title.lower() for f in report.blocking_findings)


def test_merge_ux_backlog_dedupes():
    existing = json.dumps(
        {"items": [{"title": "Better empty states", "description": "Add CTA", "source": "user_journey"}]}
    )
    merged = merge_ux_improvement_backlog(
        existing,
        [
            UserJourneyFinding(
                severity="low",
                category="ux_improvement",
                title="Better empty states",
                description="Duplicate",
            ),
            UserJourneyFinding(
                severity="medium",
                category="ux_improvement",
                title="Add keyboard shortcuts",
                description="Power users want shortcuts",
            ),
        ],
    )
    titles = [item["title"] for item in merged["items"]]
    assert titles.count("Better empty states") == 1
    assert "Add keyboard shortcuts" in titles


def test_format_blocking_failure_includes_findings():
    report = UserJourneyReport(
        passed=False,
        blocking_findings=[
            UserJourneyFinding(
                severity="high",
                category="blocking",
                title="Cannot create items",
                description="POST failed",
            )
        ],
    )
    text = format_blocking_failure(report)
    assert "Cannot create items" in text
    assert "Fix these issues" in text


@pytest.mark.asyncio
async def test_persist_user_journey_results_writes_artifacts():
    from app.services.user_journey_testing import persist_user_journey_results

    workspace = MagicMock()
    workspace.list_artifacts.return_value = []
    project_id = uuid4()
    report = UserJourneyReport(
        passed=True,
        ux_improvements=[
            UserJourneyFinding(
                severity="low",
                category="ux_improvement",
                title="Polish loading states",
                description="Add skeletons",
            )
        ],
    )
    await persist_user_journey_results(workspace, project_id, report)
    assert workspace.write_artifact.call_count == 2
    assert workspace.write_artifact.call_args_list[0].args[1] == "user-journey-report.json"
