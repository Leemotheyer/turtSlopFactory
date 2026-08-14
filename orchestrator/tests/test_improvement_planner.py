"""Tests for autonomous improvement planning."""

from app.services.improvement_planner import plan_improvements


def test_first_iteration_suggests_mobile_and_ux():
    items = plan_improvements(
        description="A web GUI docker app for home lab",
        notes=[],
        iteration=1,
        max_items=3,
    )
    assert len(items) >= 2
    categories = {i.category for i in items}
    assert "mobile" in categories or "ux" in categories


def test_skips_duplicate_features_in_notes():
    notes = [
        {"type": "feature", "content": "Mobile-responsive layout for phones"},
        {"type": "instruction", "content": "Keep it simple"},
    ]
    items = plan_improvements(
        description="Web app",
        notes=notes,
        iteration=1,
        max_items=3,
    )
    titles = " ".join(i.title.lower() for i in items)
    assert "mobile-responsive" not in titles


def test_review_concerns_prioritized():
    review = '{"decision": "reject", "concerns": ["Missing pagination on item list"]}'
    items = plan_improvements(
        description="Web app",
        notes=[],
        iteration=2,
        review_artifact=review,
        max_items=2,
    )
    assert any("pagination" in i.description.lower() for i in items)


def test_later_iterations_add_polish():
    items = plan_improvements(
        description="Docker web app",
        notes=[{"type": "feature", "content": f"done-{i}"} for i in range(20)],
        iteration=5,
        max_items=2,
    )
    assert len(items) <= 2
