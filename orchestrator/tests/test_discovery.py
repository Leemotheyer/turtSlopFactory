from app.agents.discovery import generate_discovery
from app.services.intake_analysis import analyze_project_description


def test_generate_discovery_returns_plan_and_fields():
    plan, fields = generate_discovery("RSS Reader", "A self-hosted RSS reader with web UI")
    assert "RSS Reader" in plan
    assert len(fields) >= 8
    ids = {f.id for f in fields}
    assert "primary_goal" in ids
    assert "must_have_features" in ids
    assert "confirm_interpretation" in ids
    assert "out_of_scope" in ids


def test_rss_keyword_adds_bespoke_questions():
    _, fields = generate_discovery("Poller", "RSS feed poller that checks every hour")
    ids = {f.id for f in fields}
    assert "poll_interval" in ids
    assert "feed_sources" in ids


def test_dashboard_domain_adds_data_questions():
    _, fields = generate_discovery(
        "Ops Dash",
        "Internal analytics dashboard with charts for API error rates and uptime metrics",
    )
    ids = {f.id for f in fields}
    assert "data_sources" in ids
    assert "key_metrics" in ids


def test_integration_mentions_add_external_integrations():
    _, fields = generate_discovery(
        "Komga Bridge",
        "Integrate with my Komga server to sync comic libraries and show reading progress",
    )
    ids = {f.id for f in fields}
    assert "external_integrations" in ids


def test_brief_description_adds_clarify_vision():
    _, fields = generate_discovery("App", "Invoice tracker")
    ids = {f.id for f in fields}
    assert "clarify_vision" in ids


def test_fields_have_categories():
    _, fields = generate_discovery("Test", "A web app for teams to manage tasks with login")
    categories = {f.category for f in fields}
    assert "vision" in categories
    assert "features" in categories


def test_analyze_extracts_features_from_description():
    analysis = analyze_project_description(
        "Tracker",
        "Build an app with export to CSV and user login for small teams",
    )
    assert analysis.mentioned_features or analysis.auth_signal == "simple"
    assert "crud_data" in analysis.domains or "auth_users" in analysis.domains


def test_existing_repo_includes_existing_category():
    repo_context = {
        "has_existing_app": True,
        "has_backend": True,
        "stack": ["FastAPI"],
        "repo_name": "owner/app",
    }
    plan, fields = generate_discovery(
        "App",
        "Add Komga integration",
        repo_context=repo_context,
        suggested_responses={"primary_goal": "Add Komga integration"},
    )
    ids = {f.id for f in fields}
    assert "existing_code_approach" in ids
    assert "gaps_to_address" in ids
    assert "Existing repository" in plan
    assert any(f.category == "existing" for f in fields)
