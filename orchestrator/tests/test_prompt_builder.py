from app.agents.prompt_builder import build_role_prompt
from app.models import AgentRole


def test_enrichment_prompt_excludes_greenfield_planning():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "Comic Reader",
            "description": "Komga proxy app",
            "original_description": "Build a Komga comic reader with web UI",
            "enrichment_pass": 1,
            "max_enrichment_passes": 4,
            "max_features_per_pass": 8,
            "preview_audit": {"health_ok": True, "has_html_ui": False, "issues": []},
        },
    )
    assert "enrichment-plan.json" in prompt
    assert "substantial" in prompt.lower()
    assert "Product vision" in prompt
    assert "Architect rules" in prompt
    assert "NOT** write requirements.md" in prompt or "NOT write requirements.md" in prompt
    assert "Create project requirements and architecture" not in prompt


def test_architect_prompt_includes_original_description():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "App",
            "description": "Refined spec after intake",
            "original_description": "Original user idea about RSS feeds",
            "repo_url": "https://github.com/o/r",
            "global_agent_rules": "- No dummy data in production",
        },
    )
    assert "Original user idea about RSS feeds" in prompt
    assert "Architect rules" in prompt
    assert "Global user rules" in prompt


def test_planning_architect_prompt_includes_requirements():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {"name": "App", "description": "Test", "repo_url": "https://github.com/o/r"},
    )
    assert "requirements.md" in prompt
    assert "enrichment-plan.json" not in prompt
