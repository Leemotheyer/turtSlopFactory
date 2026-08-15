from app.services.agent_activity import _cursor_url, _summarize_event
from app.models import EventType


def test_cursor_url_only_for_cloud_agent_ids():
    assert _cursor_url("bc-abc123") == "https://cursor.com/agents/bc-abc123"
    assert _cursor_url("architect-eb1e2cea") is None
    assert _cursor_url("cursor_cloud-architect-eb1e2cea") is None
    assert _cursor_url("cursor_local-dev-1") is None
    assert _cursor_url(None) is None
    assert _cursor_url("bc-1", "https://cursor.com/agents/bc-1?tab=review") == (
        "https://cursor.com/agents/bc-1?tab=review"
    )


def test_remember_task_agent_prefers_cloud_id_over_placeholder():
    from app.services.agent_activity import _remember_task_agent

    agent_ids: dict[str, str] = {}
    cursor_urls: dict[str, str] = {}
    tid = "task-1"
    _remember_task_agent(agent_ids, cursor_urls, tid, "architect-50013585")
    _remember_task_agent(agent_ids, cursor_urls, tid, "bc-real-agent-id")
    assert agent_ids[tid] == "bc-real-agent-id"
    assert cursor_urls[tid] == "https://cursor.com/agents/bc-real-agent-id"

    agent_ids = {}
    cursor_urls = {}
    _remember_task_agent(agent_ids, cursor_urls, tid, "bc-real-agent-id")
    _remember_task_agent(agent_ids, cursor_urls, tid, "architect-50013585")
    assert agent_ids[tid] == "bc-real-agent-id"


def test_summarize_agent_started_event():
    summary = _summarize_event(
        EventType.AGENT_COMMAND_STARTED.value,
        {"role": "developer", "title": "Build API"},
    )
    assert "developer" in summary
    assert "Build API" in summary


def test_summarize_pipeline_stopped_event():
    summary = _summarize_event(EventType.PIPELINE_STOPPED.value, {})
    assert summary == "Pipeline stopped"


def test_summarize_agent_output_event():
    summary = _summarize_event(
        EventType.AGENT_COMMAND_OUTPUT.value,
        {"role": "architect", "status": "thinking"},
    )
    assert "architect" in summary
    assert "thinking" in summary
