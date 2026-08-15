"""Track completed pipeline work units to avoid redundant agent runs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.services.work_planner import WorkUnit, _slugify
from app.workspace.manager import WorkspaceManager

DEFAULT_BOOTSTRAP_FEATURES = frozenset({"ux-polish", "core-completeness"})


def work_unit_key(unit: WorkUnit) -> str:
    if unit.feature_id:
        return unit.feature_id
    return unit.stream


def load_completed_work(workspace: WorkspaceManager, project_id: UUID) -> set[str]:
    meta = workspace.load_metadata(project_id)
    raw = meta.get("completed_work") or []
    return {str(item) for item in raw}


def mark_work_unit_complete(workspace: WorkspaceManager, project_id: UUID, unit: WorkUnit) -> None:
    meta = workspace.load_metadata(project_id)
    completed = set(meta.get("completed_work") or [])
    completed.add(work_unit_key(unit))
    meta["completed_work"] = sorted(completed)
    workspace.save_metadata(project_id, meta)


def repo_has_backend(repo: Path) -> bool:
    main_py = repo / "app" / "main.py"
    return main_py.is_file() and main_py.stat().st_size > 100


def repo_has_frontend(repo: Path) -> bool:
    static = repo / "app" / "static"
    if not static.is_dir():
        return False
    for path in static.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".js", ".css"}:
            return True
    return False


def feature_note_slug(note: dict) -> str:
    return _slugify((note.get("content") or "").strip())


def filter_units_for_feedback(
    units: list[WorkUnit],
    *,
    completed: set[str],
    repo: Path | None,
) -> list[WorkUnit]:
    """Drop work already done when iterating from REVIEW feedback."""
    if not completed and not (repo and repo_has_backend(repo)):
        return units

    filtered: list[WorkUnit] = []
    for unit in units:
        key = work_unit_key(unit)
        if key in completed:
            continue
        if unit.stream == "backend" and repo and repo_has_backend(repo):
            continue
        if unit.stream == "frontend" and repo and repo_has_frontend(repo):
            continue
        if unit.stream == "feature" and key in DEFAULT_BOOTSTRAP_FEATURES and key in completed:
            continue
        filtered.append(unit)
    return filtered
