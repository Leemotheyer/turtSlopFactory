"""Agent-assisted repository exploration when static analysis is inconclusive."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.factory import create_agent_runner
from app.db_models import ProjectRow
from app.models import AgentRole
from app.services.repo_analysis import analyze_repo
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_EXPLORATION_ARTIFACT = "repo-exploration.json"
_MAX_TREE_LINES = 120
_MAX_SAMPLE_BYTES = 4000


def repo_has_content(repo: Path, analysis: dict[str, Any], github_meta: dict[str, Any] | None = None) -> bool:
    github_meta = github_meta or {}
    if not repo.is_dir():
        return False
    if (repo / ".git").exists() and any(repo.iterdir()):
        pass
    return bool(
        analysis.get("source_file_count", 0) > 0
        or analysis.get("top_level_entries")
        or (analysis.get("readme_excerpt") or "").strip()
        or (github_meta.get("size_kb") or 0) > 0
        or any(p.name not in {".git"} for p in repo.iterdir() if p.exists())
    )


def needs_agent_repo_exploration(
    repo: Path,
    analysis: dict[str, Any],
    github_meta: dict[str, Any] | None = None,
) -> bool:
    """True when the repo clearly has files but static heuristics are uncertain."""
    if not repo_has_content(repo, analysis, github_meta):
        return False
    if analysis.get("exploration_completed"):
        return False

    has_stack = bool(analysis.get("stack"))
    has_shape = bool(analysis.get("has_backend") or analysis.get("has_frontend") or analysis.get("entry_points"))
    confident_static = analysis.get("has_existing_app") and has_stack and has_shape

    return not confident_static


def _extract_json_block(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _repo_tree(repo: Path, *, max_depth: int = 4) -> list[str]:
    lines: list[str] = []

    def walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth or len(lines) >= _MAX_TREE_LINES:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for entry in entries:
            if entry.name in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}:
                continue
            rel = entry.relative_to(repo)
            lines.append(f"{prefix}{rel}{'/' if entry.is_dir() else ''}")
            if entry.is_dir():
                walk(entry, prefix + "  ", depth + 1)

    walk(repo, "", 0)
    return lines


def _sample_key_files(repo: Path) -> str:
    samples: list[str] = []
    candidates = (
        "README.md",
        "readme.md",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "Makefile",
        "docker-compose.yml",
        "Dockerfile",
    )
    for name in candidates:
        path = repo / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:_MAX_SAMPLE_BYTES]
        except OSError:
            continue
        samples.append(f"### {name}\n```\n{text}\n```")
    return "\n\n".join(samples)


def explore_repo_locally(repo: Path, description: str = "") -> dict[str, Any]:
    """Deterministic fallback when no Cursor agent is available."""
    tree = _repo_tree(repo)
    samples = _sample_key_files(repo)
    analysis = analyze_repo(repo)

    stack = list(analysis.get("stack") or [])
    summary_parts = []
    if stack:
        summary_parts.append(f"Detected stack hints: {', '.join(stack)}")
    if analysis.get("readme_excerpt"):
        summary_parts.append("README present with documented capabilities.")
    if analysis.get("source_file_count", 0):
        summary_parts.append(f"{analysis['source_file_count']} source files under version control.")
    if not summary_parts:
        summary_parts.append("Repository contains files but layout did not match factory defaults.")

    how_to = (
        "Inspect the directory tree and key config files, identify the primary entry points, "
        "run existing tests if present, then implement only the gaps from the project description."
    )
    if description.strip():
        how_to = (
            f"Continue the existing codebase toward: {description.strip()[:400]}. "
            "Preserve working behavior; change only what the description requires."
        )

    return {
        "method": "local_heuristic",
        "project_type": "unknown",
        "summary": " ".join(summary_parts),
        "stack": stack,
        "has_backend": bool(analysis.get("has_backend")),
        "has_frontend": bool(analysis.get("has_frontend")),
        "has_tests": bool(analysis.get("has_tests")),
        "entry_points": analysis.get("entry_points") or [],
        "detected_features": analysis.get("detected_features") or [],
        "what_works_today": _infer_what_works(analysis, tree),
        "gaps_from_description": description.strip()[:800] if description.strip() else "",
        "recommended_approach": "Extend existing code (recommended)",
        "how_to_progress": how_to,
        "preserve_paths": analysis.get("preserve_paths") or [],
        "confidence": "medium" if stack or analysis.get("source_file_count", 0) >= 3 else "low",
        "directory_tree": tree,
        "file_samples_included": bool(samples),
        "_prompt_context": f"## Directory tree\n" + "\n".join(tree[:80]) + ("\n\n" + samples if samples else ""),
    }


def _infer_what_works(analysis: dict[str, Any], tree: list[str]) -> str:
    parts: list[str] = []
    if analysis.get("stack"):
        parts.append(f"Stack: {', '.join(analysis['stack'])}")
    if analysis.get("has_backend"):
        parts.append("Server/backend code present")
    if analysis.get("has_frontend"):
        parts.append("UI/frontend present")
    if analysis.get("has_tests"):
        parts.append("Tests present")
    if tree:
        parts.append(f"Top-level layout includes: {', '.join(tree[:8])}")
    return "; ".join(parts) if parts else "Existing files present — structure needs manual confirmation in intake."


def build_repo_exploration_prompt(
    project_name: str,
    description: str,
    static_analysis: dict[str, Any],
    *,
    local_context: str = "",
) -> str:
    readme = (static_analysis.get("readme_excerpt") or "")[:2500]
    top = ", ".join(static_analysis.get("top_level_entries") or []) or "(empty)"
    return f"""You are the **architect** agent performing **repository exploration only** for turtSlopFactory.

The factory linked an existing GitHub repository but static analysis could not confidently classify its structure.
Your job is to **read the codebase** and explain what it is and **how the factory should continue** — not to rewrite it.

## Project
- Name: {project_name}
- User description / goal: {description.strip() or "(none yet)"}

## Static scan (may be incomplete)
- Source files counted: {static_analysis.get("source_file_count", 0)}
- Top level: {top}
- Stack hints: {", ".join(static_analysis.get("stack") or []) or "none"}
- Backend hint: {static_analysis.get("has_backend")}
- Frontend hint: {static_analysis.get("has_frontend")}

## README excerpt
{readme or "(no README found locally)"}

{local_context}

## Your task
Explore the repository. Read key source files, configs, and docs. Then reply with **only** a JSON object (optionally in a ```json fence):

```json
{{
  "project_type": "web_app | api | library | monorepo | cli | unknown",
  "summary": "2-4 sentences on what this repo already is",
  "stack": ["languages/frameworks detected"],
  "has_backend": true,
  "has_frontend": false,
  "has_tests": true,
  "entry_points": ["paths to main apps or services"],
  "detected_features": ["capabilities already implemented"],
  "what_works_today": "What should be preserved",
  "gaps_from_description": "What the user's description implies still needs doing",
  "recommended_approach": "Extend existing code (recommended)",
  "how_to_progress": "Concrete next steps for factory agents on this repo",
  "preserve_paths": ["directories or files not to replace"],
  "confidence": "high | medium | low"
}}
```

Rules:
- Do **NOT** write requirements.md, architecture.md, or greenfield scaffold plans.
- Do **NOT** delete or replace working code — this is reconnaissance for a **continue existing project** flow.
- Be specific about entry points, stack, and what already works.
- If the repo is mostly docs/config with little code, say so and recommend minimal changes.
"""


def normalize_exploration_payload(raw: dict[str, Any], *, method: str = "agent") -> dict[str, Any]:
    return {
        "method": method,
        "project_type": str(raw.get("project_type") or "unknown"),
        "summary": str(raw.get("summary") or "").strip(),
        "stack": [str(s) for s in (raw.get("stack") or []) if s][:12],
        "has_backend": bool(raw.get("has_backend")),
        "has_frontend": bool(raw.get("has_frontend")),
        "has_tests": bool(raw.get("has_tests")),
        "entry_points": [str(p) for p in (raw.get("entry_points") or []) if p][:12],
        "detected_features": [str(f) for f in (raw.get("detected_features") or []) if f][:12],
        "what_works_today": str(raw.get("what_works_today") or "").strip(),
        "gaps_from_description": str(raw.get("gaps_from_description") or "").strip(),
        "recommended_approach": str(raw.get("recommended_approach") or "Extend existing code (recommended)"),
        "how_to_progress": str(raw.get("how_to_progress") or "").strip(),
        "preserve_paths": [str(p) for p in (raw.get("preserve_paths") or []) if p][:16],
        "confidence": str(raw.get("confidence") or "medium"),
    }


def apply_exploration_to_analysis(analysis: dict[str, Any], exploration: dict[str, Any]) -> dict[str, Any]:
    merged = {**analysis}
    stack = list(dict.fromkeys((analysis.get("stack") or []) + (exploration.get("stack") or [])))
    features = list(
        dict.fromkeys((analysis.get("detected_features") or []) + (exploration.get("detected_features") or []))
    )
    entry_points = list(
        dict.fromkeys((analysis.get("entry_points") or []) + (exploration.get("entry_points") or []))
    )
    preserve = list(
        dict.fromkeys((analysis.get("preserve_paths") or []) + (exploration.get("preserve_paths") or []))
    )

    merged.update(
        {
            "has_existing_app": True,
            "has_substantial_codebase": True,
            "continuation_mode": "extend",
            "stack": stack,
            "detected_features": features,
            "entry_points": entry_points,
            "preserve_paths": preserve,
            "has_backend": bool(analysis.get("has_backend") or exploration.get("has_backend")),
            "has_frontend": bool(analysis.get("has_frontend") or exploration.get("has_frontend")),
            "has_tests": bool(analysis.get("has_tests") or exploration.get("has_tests")),
            "exploration_completed": True,
            "exploration_method": exploration.get("method", "agent"),
            "exploration_confidence": exploration.get("confidence", "medium"),
            "agent_summary": exploration.get("summary", ""),
            "how_to_progress": exploration.get("how_to_progress", ""),
            "project_type": exploration.get("project_type", "unknown"),
        }
    )
    if exploration.get("what_works_today"):
        merged["what_works_today"] = exploration["what_works_today"]
    if exploration.get("gaps_from_description"):
        merged["gaps_from_description"] = exploration["gaps_from_description"]
    if exploration.get("recommended_approach"):
        merged["recommended_approach"] = exploration["recommended_approach"]
    return merged


def enrich_intake_from_exploration(
    suggested: dict[str, str | list[str]],
    exploration: dict[str, Any],
    description: str,
) -> dict[str, str | list[str]]:
    out = dict(suggested)
    if exploration.get("what_works_today"):
        out["what_works_today"] = exploration["what_works_today"]
    if exploration.get("recommended_approach"):
        out["existing_code_approach"] = exploration["recommended_approach"]
    gaps = exploration.get("gaps_from_description") or description.strip()
    progress = exploration.get("how_to_progress") or ""
    parts = [p for p in (gaps, progress) if p]
    if parts:
        out["gaps_to_address"] = "\n\n".join(parts)
    if exploration.get("summary"):
        out["anything_else"] = (
            f"Agent repo exploration: {exploration['summary']}\n\n"
            "Continue the existing codebase — do not greenfield scaffold."
        )
    if exploration.get("detected_features") and not out.get("must_have_features"):
        out["must_have_features"] = "\n".join(
            f"- {f}" for f in exploration["detected_features"][:8]
        )
    return out


async def explore_repo_with_agent(
    session: AsyncSession,
    project: ProjectRow,
    repo_path: Path,
    static_analysis: dict[str, Any],
    workspace: WorkspaceManager,
) -> dict[str, Any]:
    """Run architect agent (or local heuristic fallback) to classify an unclear repo."""
    local = explore_repo_locally(repo_path, project.description or "")
    local_context = local.pop("_prompt_context", "")

    runner = create_agent_runner(workspace)
    task_id = uuid4()
    context = {
        "name": project.name,
        "description": project.description or "",
        "original_description": project.description or "",
        "repo_url": project.repo_url,
        "repo_analysis": static_analysis,
        "repo_exploration": True,
        "repo_exploration_prompt": build_repo_exploration_prompt(
            project.name,
            project.description or "",
            static_analysis,
            local_context=local_context,
        ),
        "notes": [],
        "intake": {},
    }

    workspace.append_log(
        project.id,
        "pipeline.log",
        "[discovery] Static repo analysis inconclusive — running architect repo exploration",
    )

    run = await runner.run(
        AgentRole.ARCHITECT,
        project.id,
        task_id,
        str(repo_path),
        context,
    )

    exploration: dict[str, Any] | None = None
    if workspace.read_artifact(project.id, _EXPLORATION_ARTIFACT):
        try:
            exploration = json.loads(workspace.read_artifact(project.id, _EXPLORATION_ARTIFACT) or "{}")
        except json.JSONDecodeError:
            exploration = None
    if not exploration and run.output:
        parsed = _extract_json_block(run.output)
        if parsed:
            exploration = normalize_exploration_payload(parsed, method="agent" if run.success else "agent_partial")

    if exploration:
        workspace.write_artifact(
            project.id,
            _EXPLORATION_ARTIFACT,
            json.dumps(exploration, indent=2),
        )
        workspace.append_log(
            project.id,
            "pipeline.log",
            f"[discovery] Repo exploration complete ({exploration.get('method')}, "
            f"confidence={exploration.get('confidence')})",
        )
        return exploration

    workspace.append_log(
        project.id,
        "pipeline.log",
        "[discovery] Agent repo exploration unavailable — using local heuristic scan",
    )
    workspace.write_artifact(project.id, _EXPLORATION_ARTIFACT, json.dumps(local, indent=2))
    return local


def load_exploration_artifact(workspace: WorkspaceManager, project_id: UUID) -> dict[str, Any] | None:
    raw = workspace.read_artifact(project_id, _EXPLORATION_ARTIFACT)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
