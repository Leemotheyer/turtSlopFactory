from pathlib import Path

import pytest

from app.services.repo_analysis import analyze_repo
from app.services.repo_exploration import (
    apply_exploration_to_analysis,
    enrich_intake_from_exploration,
    explore_repo_locally,
    needs_agent_repo_exploration,
    normalize_exploration_payload,
)


def test_needs_exploration_for_unusual_layout(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Docs only\n")
    (tmp_path / "LICENSE").write_text("MIT")
    analysis = analyze_repo(tmp_path)
    assert not analysis["has_existing_app"]
    assert needs_agent_repo_exploration(tmp_path, analysis, {"size_kb": 10})


def test_skips_exploration_when_static_confident(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    analysis = analyze_repo(tmp_path)
    assert analysis["has_existing_app"]
    assert not needs_agent_repo_exploration(tmp_path, analysis)


def test_local_exploration_produces_json(tmp_path: Path):
    (tmp_path / "unknown_tool").mkdir()
    (tmp_path / "unknown_tool" / "run.sh").write_text("#!/bin/bash\necho hi\n")
    (tmp_path / "README.md").write_text("# Custom tool\n\n- Does things\n")
    result = explore_repo_locally(tmp_path, "Add logging")
    assert result["method"] == "local_heuristic"
    assert result["what_works_today"]
    assert "logging" in result["how_to_progress"].lower() or "logging" in result["gaps_from_description"].lower()


def test_apply_exploration_marks_existing(tmp_path: Path):
    base = analyze_repo(tmp_path)
    exploration = normalize_exploration_payload(
        {
            "summary": "A Rust CLI tool",
            "stack": ["Rust"],
            "has_backend": True,
            "entry_points": ["src/main.rs"],
            "what_works_today": "CLI parses args",
            "how_to_progress": "Add subcommand for export",
        },
        method="agent",
    )
    merged = apply_exploration_to_analysis(base, exploration)
    assert merged["has_existing_app"]
    assert merged["exploration_completed"]
    assert "Rust" in merged["stack"]
    assert merged["what_works_today"] == "CLI parses args"


def test_enrich_intake_from_exploration():
    exploration = {
        "what_works_today": "Auth works",
        "gaps_from_description": "Add billing",
        "how_to_progress": "Extend API module",
        "recommended_approach": "Extend existing code (recommended)",
        "summary": "SaaS app with auth",
        "detected_features": ["Login"],
    }
    out = enrich_intake_from_exploration({}, exploration, "Add billing")
    assert out["what_works_today"] == "Auth works"
    assert "billing" in out["gaps_to_address"].lower()
    assert "Agent repo exploration" in out["anything_else"]
