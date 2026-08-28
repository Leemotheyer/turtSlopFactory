from pathlib import Path

import pytest

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
    assert analysis["continuation_mode"] == "extend"
    assert analysis["has_backend"]
    assert analysis["has_frontend"]
    assert "FastAPI" in analysis["stack"]
    assert analysis["detected_features"]


def test_analyze_repo_detects_nextjs_monorepo(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        '{"name":"app","dependencies":{"next":"14.0.0","react":"18.0.0"}}'
    )
    (tmp_path / "next.config.js").write_text("module.exports = {};\n")
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
        (src / f"page{i}.tsx").write_text(f"export default function P{i}() {{ return null }}\n")

    analysis = analyze_repo(tmp_path)
    assert analysis["has_existing_app"]
    assert analysis["has_substantial_codebase"]
    assert analysis["has_frontend"]
    assert "Next.js" in analysis["stack"]
    assert analysis["source_file_count"] >= 10


def test_analyze_repo_substantial_python_without_fastapi_layout(tmp_path: Path):
    pkg = tmp_path / "myproject"
    pkg.mkdir()
    for i in range(12):
        (pkg / f"module_{i}.py").write_text(f"def fn_{i}():\n    return {i}\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'myproject'\n")

    analysis = analyze_repo(tmp_path)
    assert analysis["has_existing_app"]
    assert analysis["has_substantial_codebase"]
    assert analysis["source_file_count"] >= 12


def test_analyze_repo_github_size_fallback(tmp_path: Path):
    analysis = analyze_repo(tmp_path, github_meta={"size_kb": 250})
    assert analysis["has_existing_app"]
    assert analysis["continuation_mode"] == "extend"


def test_infer_intake_defaults_existing_repo(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "README.md").write_text("# Tool\n\n- Export CSV\n- User login\n")
    analysis = analyze_repo(tmp_path)
    defaults = infer_intake_defaults("Add Komga integration", analysis)
    assert defaults.get("existing_code_approach") == "Extend existing code (recommended)"
    assert defaults.get("what_works_today")
    assert defaults.get("gaps_to_address")
    assert "do not rebuild" in defaults.get("anything_else", "").lower()


def test_generate_discovery_existing_repo_fields():
    repo_context = {
        "has_existing_app": True,
        "has_backend": True,
        "has_frontend": True,
        "stack": ["FastAPI"],
        "repo_name": "owner/app",
        "source_file_count": 42,
    }
    plan, fields = generate_discovery(
        "App",
        "Add Komga integration",
        repo_context=repo_context,
        suggested_responses={"primary_goal": "Add Komga integration"},
    )
    ids = {f.id for f in fields}
    assert "existing_code_approach" in ids
    assert "what_works_today" in ids
    assert "gaps_to_address" in ids
    assert "Existing repository" in plan
    assert "Source files scanned: 42" in plan
