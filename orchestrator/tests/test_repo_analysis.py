from pathlib import Path

from app.agents.discovery import generate_discovery
from app.services.repo_analysis import analyze_repo, infer_intake_defaults


def test_analyze_repo_detects_fastapi_app(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "app" / "static").mkdir()
    (tmp_path / "app" / "static" / "index.html").write_text("<html></html>")
    (tmp_path / "requirements.txt").write_text("fastapi\npytest\n")
    (tmp_path / "README.md").write_text("# App\n\n- List items\n- Create items\n")

    analysis = analyze_repo(tmp_path)
    assert analysis["has_existing_app"]
    assert analysis["has_backend"]
    assert analysis["has_frontend"]
    assert "FastAPI" in analysis["stack"]
    assert analysis["detected_features"]


def test_infer_intake_defaults_from_readme(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Tool\n\n- Export CSV\n- User login\n")
    analysis = analyze_repo(tmp_path)
    defaults = infer_intake_defaults("Track my comics", analysis)
    assert defaults.get("primary_goal") == "Track my comics"
    assert "Export CSV" in str(defaults.get("must_have_features", ""))


def test_generate_discovery_existing_repo_fields():
    repo_context = {
        "has_existing_app": True,
        "has_backend": True,
        "has_frontend": True,
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
