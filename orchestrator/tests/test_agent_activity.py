from app.services.agent_activity import _summarize_event
from app.models import EventType


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
