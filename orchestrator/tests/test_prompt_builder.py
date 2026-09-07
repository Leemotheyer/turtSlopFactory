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
    assert "milestone" in prompt.lower()
    assert "architect" in prompt.lower()
    assert "NOT** write requirements.md" in prompt or "NOT write requirements.md" in prompt
    assert "Create project requirements and architecture" not in prompt


def test_enrichment_prompt_allows_two_milestones_in_post_production():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "Clicker",
            "description": "Idle game",
            "enrichment_pass": 1,
            "max_enrichment_passes": 3,
            "max_features_per_pass": 8,
            "max_milestones_per_pass": 2,
            "preview_audit": {"health_ok": True, "has_html_ui": True, "issues": []},
        },
    )
    assert "one or two" in prompt.lower()


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


def test_user_perspective_review_prompt_includes_cycle_label():
    prompt = build_role_prompt(
        AgentRole.TESTER,
        {
            "name": "App",
            "description": "Todo app",
            "test_stage": "user_perspective_review",
            "cycle_label": "improvement cycle 2",
            "preview_upstream": "http://preview:8080",
            "preview_audit": {"health_ok": True, "has_html_ui": True},
        },
    )
    assert "user-perspective-review.json" in prompt
    assert "improvement cycle 2" in prompt
    assert "suggestions" in prompt.lower()


def test_enrichment_prompt_includes_improvement_backlog():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "App",
            "description": "App",
            "enrichment_pass": 1,
            "max_enrichment_passes": 4,
            "max_features_per_pass": 8,
            "preview_audit": {"health_ok": True, "has_html_ui": True, "issues": []},
            "improvement_backlog": [
                {
                    "title": "Add dark mode",
                    "description": "Theme toggle in settings",
                    "category": "ui",
                }
            ],
        },
    )
    assert "dark mode" in prompt.lower()
    assert "prior review" in prompt.lower()


def test_enrichment_prompt_includes_product_qa_feedback():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {
            "name": "Manga app",
            "description": "Search and download manga",
            "enrichment_pass": 2,
            "max_enrichment_passes": 4,
            "max_features_per_pass": 8,
            "preview_audit": {"health_ok": True, "has_html_ui": True, "issues": []},
            "product_qa_feedback": {
                "issues": [
                    "Intake requires data/search/download flows but the live preview "
                    "only exposes a minimal API surface"
                ],
                "suggested_features": ["Add catalog search and chapter download APIs"],
            },
        },
    )
    assert "Product QA" in prompt
    assert "minimal API surface" in prompt
    assert "catalog search" in prompt.lower()


def test_planning_architect_prompt_includes_requirements():
    prompt = build_role_prompt(
        AgentRole.ARCHITECT,
        {"name": "App", "description": "Test", "repo_url": "https://github.com/o/r"},
    )
    assert "requirements.md" in prompt
    assert "enrichment-plan.json" not in prompt
    assert "feature-rich" in prompt.lower()
    assert "at least 8" in prompt.lower()


def test_role_profiles_reduce_prompt_size():
    rich_context = {
        "name": "App",
        "description": "A full-stack manga reader with search, download, and library sync",
        "original_description": "Manga app",
        "repo_url": "https://github.com/o/r",
        "intake": {"must_have_features": "Search\nDownload\nLibrary sync"},
        "contract": type(
            "C",
            (),
            {
                "goal": "Build a manga reader",
                "requirements": [
                    type(
                        "R",
                        (),
                        {
                            "id": "R1",
                            "priority": "must",
                            "description": "Search catalog",
                            "acceptance": ["GET /api/search returns results"],
                        },
                    )()
                ],
                "non_goals": [],
            },
        )(),
        "project_memory": {
            "decisions": [{"decision": "Use FastAPI", "reason": "default"}],
            "known_issues": [],
            "recent_failures": [],
        },
        "git_history": "abc123 commit\n" * 40,
        "preview_url": "http://localhost/preview",
        "preview_upstream": "http://preview:8080",
        "preview_audit": {"health_ok": True, "has_html_ui": True, "issues": []},
        "global_agent_rules": "- No dummy data",
    }

    planning = build_role_prompt(AgentRole.ARCHITECT, rich_context)
    enrichment = build_role_prompt(
        AgentRole.ARCHITECT, {**rich_context, "enrichment_pass": 1, "max_enrichment_passes": 4}
    )
    feature_dev = build_role_prompt(
        AgentRole.DEVELOPER,
        {
            **rich_context,
            "work_stream": "feature",
            "feature_content": "Implement search API",
        },
    )
    fix_dev = build_role_prompt(
        AgentRole.DEVELOPER,
        {
            **rich_context,
            "prompt_focus": "fix",
            "fix_brief": "- Missing search API",
            "incremental": True,
        },
    )
    tester = build_role_prompt(
        AgentRole.TESTER, {**rich_context, "test_stage": "unit"}
    )
    reviewer = build_role_prompt(AgentRole.REVIEWER, rich_context)

    assert len(enrichment) < len(planning)
    assert len(feature_dev) < len(planning)
    assert len(fix_dev) < len(feature_dev)
    assert len(tester) < len(planning)
    assert len(reviewer) < len(planning)
    assert "git history" not in enrichment.lower()
    assert "git history" not in tester.lower()
    assert "git history" not in reviewer.lower()
