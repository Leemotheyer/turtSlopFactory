import pytest

from app.config import settings
from app.services.product_enrichment import (
    audit_live_preview,
    classify_scope,
    enrichment_change_summary,
    enrichment_pass_theme_hint,
    features_to_work_units,
    local_enrichment_plan,
    parse_enrichment_plan,
    resolve_feature_scope,
)


def test_classify_scope_uncertain_for_payments():
    assert classify_scope("Stripe billing", "Add subscription checkout") == "uncertain"
    assert classify_scope("Item list", "Show items in a table") == "in_scope"


def test_classify_scope_in_scope_when_intake_requested_payments():
    intake = {"must_have_features": "Stripe subscription billing and checkout"}
    assert classify_scope("Stripe billing", "Add subscription checkout", intake=intake) == "in_scope"


def test_resolve_feature_scope_overrides_architect_uncertain_with_intake():
    intake = {"must_have_features": "Search manga catalog and download chapters"}
    scope = resolve_feature_scope(
        "Manga search",
        "Search catalog by title",
        declared_scope="uncertain",
        intake=intake,
    )
    assert scope == "in_scope"


def test_features_to_work_units_includes_intake_specified_oauth_without_approval():
    intake = {"must_have_features": "OAuth login with Google"}
    features = [{"title": "OAuth login", "description": "Google sign-in", "scope": "uncertain"}]
    units = features_to_work_units(features, intake=intake)
    assert len(units) == 1


def test_parse_enrichment_plan_json_block():
    raw = 'Here is the plan:\n```json\n{"features": [{"title": "X", "description": "Y", "scope": "in_scope"}], "quality_issues": []}\n```'
    plan = parse_enrichment_plan(raw)
    assert len(plan["features"]) == 1


def test_features_to_work_units_skips_uncertain():
    features = [{"title": "OAuth login", "description": "Google sign-in", "scope": "uncertain"}]
    assert features_to_work_units(features) == []


def test_features_to_work_units_includes_approved_uncertain():
    features = [{"title": "OAuth login", "description": "Google sign-in", "scope": "uncertain"}]
    responses = [{"question": "Implement OAuth login?", "resolved_decision": "Yes, implement it"}]
    units = features_to_work_units(features, input_responses=responses)
    assert len(units) == 1


def test_features_to_work_units_batches_multiple_features():
    features = [
        {
            "id": f"feat-{i}",
            "title": f"Feature {i}",
            "description": "Do substantial work " * 5,
            "scope": "in_scope",
            "tier": "polish",
        }
        for i in range(6)
    ]
    features[0]["tier"] = "milestone"
    units = features_to_work_units(features)
    batch_size = max(2, settings.enrichment_features_per_agent)
    expected_batches = (len(features) - 1 + batch_size - 1) // batch_size
    assert len(units) == 1 + expected_batches
    assert units[0].tier == "milestone"
    assert "Implement **all**" in (units[1].feature_content or "")


def test_features_to_work_units_promotes_first_when_no_milestone():
    features = [
        {"id": "a", "title": "Alpha", "description": "First substantial work " * 5, "scope": "in_scope"},
        {"id": "b", "title": "Beta", "description": "Second substantial work " * 5, "scope": "in_scope"},
    ]
    units = features_to_work_units(features)
    assert len(units) == 2
    assert units[0].tier == "milestone"
    assert units[0].title.startswith("Milestone:")


def test_features_to_work_units_milestone_is_solo_unit():
    features = [
        {
            "id": "big-idea",
            "title": "Export library",
            "description": "Add full export workflow with formats and progress UI",
            "scope": "in_scope",
            "tier": "milestone",
        },
        {
            "id": "polish-1",
            "title": "Loading states",
            "description": "Add skeleton loaders on list pages",
            "scope": "in_scope",
            "tier": "polish",
        },
    ]
    units = features_to_work_units(features)
    assert len(units) == 2
    assert units[0].tier == "milestone"
    assert "milestone expansion" in (units[0].feature_content or "").lower()


def test_features_to_work_units_skips_completed_slugs():
    features = [
        {"id": "core-flows", "title": "Core flows", "description": "Build CRUD", "scope": "in_scope"},
        {"id": "search", "title": "Search", "description": "Add search UI", "scope": "in_scope"},
    ]
    units = features_to_work_units(features, completed_slugs={"core-flows"})
    assert len(units) == 1
    assert "Search" in units[0].title or "search" in (units[0].feature_content or "").lower()


def test_enrichment_change_summary_lists_deliverables():
    features = [
        {"id": "a", "title": "Alpha", "description": "First", "scope": "in_scope"},
        {"id": "b", "title": "Beta", "description": "Second", "scope": "in_scope"},
        {"id": "c", "title": "Gamma", "description": "Third", "scope": "in_scope"},
    ]
    units = features_to_work_units(features)
    summary = enrichment_change_summary(units)
    assert summary
    assert any("Alpha" in line or "•" in line for line in summary)


def test_enrichment_pass_theme_hint_includes_pass_number():
    hint = enrichment_pass_theme_hint(1)
    assert "Pass 1" in hint
    assert "milestone" in hint.lower()


def test_local_enrichment_plan_uses_pass_themes():
    audit = {
        "health_ok": True,
        "has_html_ui": True,
        "endpoints": [{"method": "GET", "path": "/api/items", "ok": True}],
    }
    plan1 = local_enrichment_plan(audit, pass_number=1)
    plan2 = local_enrichment_plan(audit, pass_number=2)
    ids1 = {f["id"] for f in plan1["features"]}
    ids2 = {f["id"] for f in plan2["features"]}
    assert ids1 != ids2
    milestones = [f for f in plan1["features"] if f.get("tier") == "milestone"]
    assert milestones
    assert milestones[0]["id"] == "core-flows"


def test_local_enrichment_plan_skips_completed():
    audit = {"health_ok": True, "has_html_ui": True, "endpoints": [{"path": "/api/items", "ok": True}]}
    plan = local_enrichment_plan(audit, pass_number=1, completed_slugs={"core-flows", "navigation-shell"})
    ids = {f["id"] for f in plan["features"]}
    assert "core-flows" not in ids
    assert "navigation-shell" not in ids


def test_local_enrichment_plan_suggests_ui_polish():
    audit = {"health_ok": True, "has_html_ui": True, "endpoints": [{"method": "GET", "path": "/api/items", "ok": True}]}
    plan = local_enrichment_plan(audit, pass_number=1)
    assert plan["features"]


@pytest.mark.asyncio
async def test_audit_live_preview_no_upstream():
    audit = await audit_live_preview({})
    assert audit["issues"]
