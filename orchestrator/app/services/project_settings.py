"""Per-project pipeline settings with factory-wide fallbacks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.db_models import ProjectRow


def resolve_change_budget_files(project: "ProjectRow") -> int:
    if project.change_budget_files is not None:
        return max(1, project.change_budget_files)
    return settings.change_budget_files


def resolve_change_budget_lines(project: "ProjectRow") -> int:
    if project.change_budget_lines is not None:
        return max(1, project.change_budget_lines)
    return settings.change_budget_lines


def resolve_max_fix_attempts(project: "ProjectRow") -> int:
    if project.max_fix_attempts is not None:
        return max(1, project.max_fix_attempts)
    return settings.max_fix_attempts


def resolve_adversary_enabled(project: "ProjectRow") -> bool:
    if project.adversary_enabled is not None:
        return bool(project.adversary_enabled)
    return settings.adversary_enabled


def should_enforce_change_budget(project: "ProjectRow", *, review_ever_approved: bool) -> bool:
    """Whether oversized changes require developer JUSTIFICATION: at review.

    Default (project unset + factory default) is unlimited — change stats are recorded
    for visibility but never block review. Set enforce_change_budget=True per project
    or ENFORCE_CHANGE_BUDGET=true at factory level to enable soft budgets.
    """
    _ = review_ever_approved  # retained for API compatibility; no longer toggles enforcement
    if project.enforce_change_budget is False:
        return False
    if project.enforce_change_budget is True:
        return True
    return settings.enforce_change_budget


def project_settings_payload(project: "ProjectRow", *, review_ever_approved: bool = False) -> dict:
    """Serializable effective settings for API responses and agent context."""
    enforced = should_enforce_change_budget(project, review_ever_approved=review_ever_approved)
    return {
        "change_budget_files": project.change_budget_files,
        "change_budget_lines": project.change_budget_lines,
        "max_fix_attempts": project.max_fix_attempts,
        "adversary_enabled": project.adversary_enabled,
        "enforce_change_budget": project.enforce_change_budget,
        "change_budget_unlimited": not enforced,
        "effective_change_budget_files": (
            resolve_change_budget_files(project) if enforced else None
        ),
        "effective_change_budget_lines": (
            resolve_change_budget_lines(project) if enforced else None
        ),
        "effective_max_fix_attempts": resolve_max_fix_attempts(project),
        "effective_adversary_enabled": resolve_adversary_enabled(project),
        "effective_user_journey_enabled": settings.user_journey_testing_enabled,
        "change_budget_enforced": enforced,
        "factory_defaults": {
            "change_budget_unlimited": not settings.enforce_change_budget,
            "change_budget_files": settings.change_budget_files,
            "change_budget_lines": settings.change_budget_lines,
            "max_fix_attempts": settings.max_fix_attempts,
            "adversary_enabled": settings.adversary_enabled,
            "user_journey_testing_enabled": settings.user_journey_testing_enabled,
            "enforce_change_budget": settings.enforce_change_budget,
        },
    }


def apply_project_settings_to_context(project: "ProjectRow", context: dict) -> None:
    review_ever_approved = bool(context.get("review_ever_approved"))
    payload = project_settings_payload(project, review_ever_approved=review_ever_approved)
    context.update(payload)
    context["effective_user_journey_enabled"] = settings.user_journey_testing_enabled
