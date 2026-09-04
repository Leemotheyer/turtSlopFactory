"""Structural system map: cached discovery output agents can reason over.

Consolidates repo analysis with a deterministic Python import graph so agents
can judge impact radius without re-reading the repository every run.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

SYSTEM_MAP_ARTIFACT = "system-map.json"

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
_MAX_FILES = 400


def build_import_graph(repo: Path) -> dict[str, list[str]]:
    """Module → imported local modules, via AST (no code execution)."""
    graph: dict[str, list[str]] = {}
    if not repo.is_dir():
        return graph

    py_files: list[Path] = []
    for path in repo.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        py_files.append(path)
        if len(py_files) >= _MAX_FILES:
            break

    local_modules = {p.relative_to(repo).with_suffix("").as_posix().replace("/", ".") for p in py_files}
    local_roots = {m.split(".")[0] for m in local_modules}

    for path in py_files:
        module = path.relative_to(repo).with_suffix("").as_posix().replace("/", ".")
        imports: set[str] = set()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            graph[module] = []
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in local_roots:
                        imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in local_roots:
                    imports.add(node.module)
        graph[module] = sorted(imports)
    return graph


def impact_radius(graph: dict[str, list[str]], module: str) -> list[str]:
    """Modules that (transitively) import ``module``."""
    reverse: dict[str, set[str]] = {}
    for src, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(src)

    seen: set[str] = set()
    frontier = [module]
    while frontier:
        current = frontier.pop()
        for dependent in reverse.get(current, ()):  # noqa: B905
            if dependent not in seen:
                seen.add(dependent)
                frontier.append(dependent)
    return sorted(seen)


def build_system_map(repo: Path, *, repo_analysis: dict | None = None) -> dict:
    graph = build_import_graph(repo)
    tests = []
    if repo.is_dir():
        tests = sorted(
            p.relative_to(repo).as_posix()
            for p in repo.rglob("test_*.py")
            if not any(part in _SKIP_DIRS for part in p.parts)
        )[:100]

    components: list[dict] = []
    if (repo / "app").is_dir():
        components.append(
            {
                "component": "backend",
                "owned_files": sorted(
                    p.relative_to(repo).as_posix() for p in (repo / "app").glob("*.py")
                )[:50],
                "risk": "high" if not tests else "medium",
            }
        )
    if (repo / "app" / "static").is_dir():
        components.append(
            {
                "component": "frontend",
                "owned_files": sorted(
                    p.relative_to(repo).as_posix() for p in (repo / "app" / "static").rglob("*")
                    if p.is_file()
                )[:50],
                "risk": "low",
            }
        )
    if (repo / "app" / "features").is_dir():
        components.append(
            {
                "component": "features",
                "owned_files": sorted(
                    p.relative_to(repo).as_posix() for p in (repo / "app" / "features").glob("*.py")
                )[:50],
                "risk": "medium",
            }
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "components": components,
        "import_graph": graph,
        "tests": tests,
        "analysis": {
            k: repo_analysis.get(k)
            for k in ("has_existing_app", "has_backend", "has_frontend", "stack", "source_file_count")
        }
        if repo_analysis
        else {},
    }


def refresh_system_map(workspace, project_id: UUID, *, repo_analysis: dict | None = None) -> dict:
    repo = workspace.repo_dir(project_id)
    system_map = build_system_map(repo, repo_analysis=repo_analysis)
    try:
        workspace.write_artifact(project_id, SYSTEM_MAP_ARTIFACT, json.dumps(system_map, indent=2))
    except Exception:
        logger.warning("Could not persist system map for %s", project_id)
    return system_map


def load_git_history(repo: Path, *, limit: int = 15) -> str:
    """Recent commit subjects — previous commits often contain the missing why."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{limit}", "--no-decorate"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def format_system_map_for_prompt(system_map: dict | None, *, budget: int = 1200) -> str:
    if not system_map:
        return ""
    lines = ["\n## System map (cached discovery)"]
    for component in system_map.get("components") or []:
        owned = component.get("owned_files") or []
        lines.append(
            f"- **{component.get('component')}** ({len(owned)} file(s), risk {component.get('risk')})"
        )
    tests = system_map.get("tests") or []
    if tests:
        lines.append(f"- tests: {', '.join(tests[:8])}{'…' if len(tests) > 8 else ''}")
    text = "\n".join(lines)
    return text[:budget]
