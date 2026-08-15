from app.agents.prompt_builder import build_role_prompt
from app.models import AgentRole


def test_enrichment_prompt_excludes_greenfield_planning():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "Comic Reader",
            "description": "Komga proxy app",
            "enrichment_pass": 1,
            "preview_audit": {"health_ok": True, "has_html_ui": False, "issues": []},
        },
    )
    assert "enrichment-plan.json" in prompt
    assert "NOT** write requirements.md" in prompt or "NOT write requirements.md" in prompt
    assert "Create project requirements and architecture" not in prompt


def test_planning_architect_prompt_includes_requirements():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {"name": "App", "description": "Test", "repo_url": "https://github.com/o/r"},
    )
    assert "requirements.md" in prompt
    assert "enrichment-plan.json" not in prompt
