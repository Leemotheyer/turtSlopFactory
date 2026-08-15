import pytest

from app.services.product_enrichment import (
    audit_live_preview,
    classify_scope,
    features_to_work_units,
    local_enrichment_plan,
    parse_enrichment_plan,
)


def test_classify_scope_uncertain_for_payments():
    assert classify_scope("Stripe billing", "Add subscription checkout") == "uncertain"
    assert classify_scope("Item list", "Show items in a table") == "in_scope"


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


def test_local_enrichment_plan_suggests_ui_polish():
    audit = {"health_ok": True, "has_html_ui": True, "endpoints": [{"method": "GET", "path": "/api/items", "ok": True}]}
    plan = local_enrichment_plan(audit, pass_number=1)
    assert plan["features"]


@pytest.mark.asyncio
async def test_audit_live_preview_no_upstream():
    audit = await audit_live_preview({})
    assert audit["issues"]
