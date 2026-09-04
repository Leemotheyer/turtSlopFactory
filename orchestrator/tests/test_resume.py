"""Tests for pipeline resume helpers and failure-handling fixes."""

from app.models import ProjectState
from app.pipeline.resume import (
    clear_completion_from_gate,
    gate_needs_preview_refresh,
    is_review_policy_failure,
    preview_type_for_context,
)
from app.pipeline.stages import SUBSTAGE_REVIEW
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
        "implementation_complete": True,
    }
    clear_completion_from_gate(context, ProjectState.SMOKE_TESTING, substage=SUBSTAGE_REVIEW)
    assert "smoke_testing_complete" not in context
    assert "acceptance_complete" not in context
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
