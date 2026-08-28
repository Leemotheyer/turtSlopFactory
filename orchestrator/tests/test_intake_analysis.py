from app.services.intake_analysis import analyze_project_description


def test_detects_multiple_domains():
    analysis = analyze_project_description(
        "Platform",
        "E-commerce shop with Stripe payments, user login, and email notifications for orders",
    )
    assert "ecommerce" in analysis.domains or "billing" in analysis.domains
    assert analysis.auth_signal in ("simple", "unclear", "oauth")


def test_suggests_out_of_scope_for_simple_crud():
    analysis = analyze_project_description("Todo", "Simple todo list web app")
    assert analysis.suggested_out_of_scope
    assert any("Payment" in s or "mobile" in s.lower() for s in analysis.suggested_out_of_scope)


def test_reference_app_extraction():
    analysis = analyze_project_description(
        "Reader",
        "RSS reader similar to Feedly but self-hosted",
    )
    assert any("Feedly" in r for r in analysis.reference_apps)
