"""Helpers for resuming a blocked pipeline and clearing stale stage state."""

from __future__ import annotations

from app.models import ProjectState
from app.pipeline.stages import (
    SUBSTAGE_ACCEPTANCE,
    SUBSTAGE_ADVERSARY,
    SUBSTAGE_ENRICHMENT,
    SUBSTAGE_REVIEW,
    SUBSTAGE_USER_JOURNEY,
)

# Completion flags cleared when resuming at/after these gates so substages
# actually re-run (otherwise a blocked review loop retries review forever
# while the staging preview has gone cold).
_SMOKE_GATE_FLAGS = (
    "smoke_testing_complete",
    "post_smoke_enrichment_complete",
    "adversary_complete",
    "acceptance_complete",
    "user_journey_complete",
)

_RESUME_REFRESH_GATES = frozenset(
    {
        ProjectState.STAGING_DEPLOY,
        ProjectState.SMOKE_TESTING,
        ProjectState.REVIEW,
    }
)


def clear_completion_from_gate(
    context: dict,
    gate: ProjectState,
    *,
    substage: str | None = None,
) -> None:
    """Drop completion markers from the resume point forward."""
    if gate in (ProjectState.STAGING_DEPLOY, ProjectState.SMOKE_TESTING, ProjectState.REVIEW):
        for key in _SMOKE_GATE_FLAGS:
            context.pop(key, None)

    if gate == ProjectState.SMOKE_TESTING and substage == SUBSTAGE_REVIEW:
        context.pop("user_journey_complete", None)
        context.pop("acceptance_complete", None)
    elif gate == ProjectState.SMOKE_TESTING and substage == SUBSTAGE_USER_JOURNEY:
        context.pop("user_journey_complete", None)
        context.pop("acceptance_complete", None)
    elif gate == ProjectState.SMOKE_TESTING and substage == SUBSTAGE_ACCEPTANCE:
        context.pop("acceptance_complete", None)
    elif gate == ProjectState.SMOKE_TESTING and substage == SUBSTAGE_ADVERSARY:
        for key in ("adversary_complete", "acceptance_complete"):
            context.pop(key, None)
    elif gate == ProjectState.SMOKE_TESTING and substage == SUBSTAGE_ENRICHMENT:
        for key in _SMOKE_GATE_FLAGS[1:]:
            context.pop(key, None)


def preview_type_for_context(context: dict) -> str:
    """Pick dev vs docker staging preview based on whether a built image exists."""
    if context.get("image_tag") or context.get("preview_backend") == "docker":
        return "docker"
    return "dev"


def gate_needs_preview_refresh(gate: ProjectState | None) -> bool:
    return gate in _RESUME_REFRESH_GATES


def is_review_policy_failure(failure_text: str) -> bool:
    text = failure_text.lower()
    return (
        "change_size_justified" in text
        or '"decision": "reject"' in text
        or "review rejected" in text
    )
