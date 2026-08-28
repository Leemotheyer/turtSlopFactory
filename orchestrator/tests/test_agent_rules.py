from app.agents.prompt_builder import build_role_prompt
from app.models import AgentRole
from app.services.agent_rules import append_agent_rules_sections, normalize_agent_rules


def test_prompt_includes_global_and_project_rules():
    prompt = build_role_prompt(
        AgentRole.DEVELOPER,
        {
            "name": "App",
            "description": "Build widgets",
            "global_agent_rules": "- No rate limiting unless asked",
            "project_agent_rules": "- Use PostgreSQL only",
        },
    )
    assert "Global user rules" in prompt
    assert "No rate limiting unless asked" in prompt
    assert "Project rules" in prompt
    assert "Use PostgreSQL only" in prompt


def test_append_agent_rules_sections_skips_empty():
    sections: list[str] = ["intro"]
    append_agent_rules_sections(sections, {})
    assert sections == ["intro"]


def test_normalize_agent_rules_truncates():
    long_text = "x" * 20000
    assert len(normalize_agent_rules(long_text)) == 10000


def test_discovery_plan_includes_rules():
    from app.agents.discovery import generate_discovery

    plan, _fields = generate_discovery(
        "App",
        "Build a dashboard",
        global_agent_rules="- Skip rate limits",
        project_agent_rules="- Real data in prod",
    )
    assert "Global factory rules" in plan
    assert "Skip rate limits" in plan
    assert "Real data in prod" in plan
