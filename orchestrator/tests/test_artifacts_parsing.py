from app.artifacts.parsing import extract_json_block, parse_agent_json
from app.artifacts.schemas import AdversaryReport, EnrichmentPlan, ReviewReport


def test_parse_bare_json():
    plan = parse_agent_json(EnrichmentPlan, '{"features": [{"id": "a", "title": "A"}]}')
    assert plan is not None
    assert plan.features[0].id == "a"


def test_parse_fenced_json_in_prose():
    reply = 'Sure!\n```json\n{"decision": "approve", "checklist": {"x": true}}\n```\nDone.'
    report = parse_agent_json(ReviewReport, reply)
    assert report is not None
    assert report.approved


def test_parse_embedded_json_without_fence():
    reply = 'preamble {"decision": "reject", "concerns": ["missing tests"]} trailer'
    report = parse_agent_json(ReviewReport, reply)
    assert report is not None
    assert not report.approved
    assert report.concerns == ["missing tests"]


def test_parse_garbage_returns_none():
    assert parse_agent_json(ReviewReport, "no json here at all") is None
    assert parse_agent_json(ReviewReport, None) is None
    assert parse_agent_json(ReviewReport, "{broken json") is None


def test_adversary_severity_normalized():
    report = parse_agent_json(
        AdversaryReport,
        '{"findings": [{"severity": "CRITICAL", "description": "boom"}]}',
    )
    assert report is not None
    # Unknown severities collapse to medium rather than failing validation.
    assert report.findings[0].severity == "medium"


def test_extract_json_block_prefers_fence():
    text = 'x {"a": 1} y ```json\n{"b": 2}\n``` z'
    assert extract_json_block(text) == '{"b": 2}'


def test_unknown_fields_ignored():
    plan = parse_agent_json(
        EnrichmentPlan, '{"features": [], "shiny_new_field": 42, "stop_reason": "done"}'
    )
    assert plan is not None
    assert plan.stop_reason == "done"
