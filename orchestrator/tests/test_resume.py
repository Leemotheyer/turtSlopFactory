"""Tests for pipeline resume helpers and failure-handling fixes."""

from uuid import uuid4

import pytest

from app.models import ProjectState
from app.pipeline.resume import (
    clear_completion_from_gate,
    clear_smoke_fix_substage,
    gate_needs_preview_refresh,
    is_review_policy_failure,
    preview_type_for_context,
    stages_from_failure,
)
from app.pipeline.stages import (
    BUILD_STAGES,
    SUBSTAGE_ACCEPTANCE,
    SUBSTAGE_ADVERSARY,
    SUBSTAGE_ENRICHMENT,
    SUBSTAGE_REVIEW,
    SUBSTAGE_USER_JOURNEY,
)
from app.pipeline.stages.acceptance import format_acceptance_fix_brief
from app.pipeline.stages.enrichment import (
    _clear_enrichment_retry_plan,
    _load_enrichment_retry_plan,
    _stash_enrichment_retry_plan,
)
from app.services.diagnosis import diagnose_failure


def test_preview_type_for_context_prefers_docker_when_image_built():
    assert preview_type_for_context({"image_tag": "factory/app:build-1"}) == "docker"
    assert preview_type_for_context({}) == "dev"


def test_gate_needs_preview_refresh_for_smoke_and_review():
    assert gate_needs_preview_refresh(ProjectState.SMOKE_TESTING) is True
    assert gate_needs_preview_refresh(ProjectState.PLANNING) is False


def test_clear_completion_from_gate_clears_smoke_substage_flags():
    context = {
        "smoke_testing_complete": True,
        "post_smoke_enrichment_complete": True,
        "adversary_complete": True,
        "acceptance_complete": True,
        "user_journey_complete": True,
        "implementation_complete": True,
    }
    clear_completion_from_gate(context, ProjectState.SMOKE_TESTING, substage=SUBSTAGE_REVIEW)
    assert "smoke_testing_complete" not in context
    assert "acceptance_complete" not in context
    assert "user_journey_complete" not in context
    assert context["implementation_complete"] is True


def test_is_review_policy_failure_detects_change_size_rejection():
    text = (
        "REJECTED: {'acceptance_verified': True, 'change_size_justified': False}"
    )
    assert is_review_policy_failure(text) is True


def test_diagnose_dead_preview_as_infra():
    result = diagnose_failure("Smoke test skipped — live preview is not running")
    assert result["error_class"] == "infra"

    result = diagnose_failure("No factory live preview is running")
    assert result["error_class"] == "infra"


def test_clear_smoke_fix_substage_clears_downstream_flags():
    context = {
        "adversary_complete": True,
        "acceptance_complete": True,
        "user_journey_complete": True,
        "user_perspective_review_complete": True,
    }
    clear_smoke_fix_substage(context, SUBSTAGE_ACCEPTANCE)
    assert "acceptance_complete" not in context
    assert "user_journey_complete" not in context
    assert "user_perspective_review_complete" not in context
    assert context["adversary_complete"] is True

    context = {
        "adversary_complete": True,
        "acceptance_complete": True,
        "user_journey_complete": True,
        "user_perspective_review_complete": True,
    }
    clear_smoke_fix_substage(context, SUBSTAGE_ADVERSARY)
    assert "adversary_complete" not in context
    assert "acceptance_complete" not in context
    assert "user_journey_complete" not in context
    assert "user_perspective_review_complete" not in context


def test_clear_smoke_fix_substage_user_journey_preserves_acceptance():
    context = {
        "acceptance_complete": True,
        "user_journey_complete": True,
        "user_perspective_review_complete": True,
    }
    clear_smoke_fix_substage(context, SUBSTAGE_USER_JOURNEY)
    assert context.get("acceptance_complete") is True
    assert "user_journey_complete" not in context
    assert "user_perspective_review_complete" not in context


def test_stages_from_failure_slices_from_failed_substage():
    smoke_only = stages_from_failure(
        BUILD_STAGES, gate=ProjectState.SMOKE_TESTING, substage=None
    )
    assert smoke_only[0].method == "_stage_smoke_testing"
    assert all(spec.gate == ProjectState.SMOKE_TESTING for spec in smoke_only)

    enrichment_only = stages_from_failure(
        BUILD_STAGES, gate=ProjectState.SMOKE_TESTING, substage=SUBSTAGE_ADVERSARY
    )
    assert enrichment_only[0].method == "_stage_adversary"
    assert enrichment_only[0].substage == SUBSTAGE_ADVERSARY

    implementing_enrichment = stages_from_failure(
        BUILD_STAGES, gate=ProjectState.IMPLEMENTING, substage=SUBSTAGE_ENRICHMENT
    )
    assert implementing_enrichment[0].method == "_stage_autonomous_enrichment"

    legacy_polish = stages_from_failure(
        BUILD_STAGES, gate=ProjectState.SMOKE_TESTING, substage=SUBSTAGE_ENRICHMENT
    )
    assert legacy_polish[0].method == "_stage_adversary"


def test_format_acceptance_fix_brief_structured():
    report = {
        "requirements": {
            "R1": {
                "status": "failed",
                "description": "Search endpoint",
                "acceptance": ["GET /api/search returns results"],
                "evidence_summary": "no passing test",
            },
            "R2": {"status": "verified", "description": "Health"},
        }
    }
    brief = format_acceptance_fix_brief(
        report,
        feature_report={"issues": ["Missing download flow"]},
        regression_gaps=[{"expected_test": "test_fix_abc.py", "summary": "crash on empty query"}],
    )
    assert "R1 [failed]" in brief
    assert "Search endpoint" in brief
    assert "Feature completeness" in brief
    assert "test_fix_abc.py" in brief
    assert "R2" not in brief
    assert len(brief) < 2000


@pytest.mark.asyncio
async def test_enrichment_retry_plan_persists_in_metadata(workspace):
    from app.pipeline.executor import PipelineExecutor

    executor = PipelineExecutor()
    executor.workspace = workspace
    project_id = uuid4()
    context: dict = {}
    plan = {"features": [{"title": "Search", "description": "Add search"}]}

    _stash_enrichment_retry_plan(executor, project_id, context, 1, plan)
    assert context["enrichment_retry_plan"]["pass_number"] == 1

    reloaded: dict = {}
    loaded = _load_enrichment_retry_plan(executor, project_id, reloaded)
    assert loaded is not None
    assert loaded["plan"]["features"][0]["title"] == "Search"

    _clear_enrichment_retry_plan(executor, project_id, context)
    assert _load_enrichment_retry_plan(executor, project_id, {}) is None
