from app.agents.discovery import generate_discovery


def test_generate_discovery_returns_plan_and_fields():
    plan, fields = generate_discovery("RSS Reader", "A self-hosted RSS reader with web UI")
    assert "RSS Reader" in plan
    assert len(fields) >= 5
    ids = {f.id for f in fields}
    assert "primary_goal" in ids
    assert "must_have_features" in ids
    assert "out_of_scope" in ids


def test_rss_keyword_adds_poll_question():
    _, fields = generate_discovery("Poller", "RSS feed poller that checks every hour")
    ids = {f.id for f in fields}
    assert "poll_interval" in ids
