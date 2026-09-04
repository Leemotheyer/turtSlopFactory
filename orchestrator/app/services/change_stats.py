"""Change-size evidence: soft budgets instead of hard change caps.

The factory prefers the smallest change that satisfies the acceptance
criteria. Instead of rejecting oversized changes, it records diff stats as
evidence and flags changes that exceed the soft budget so the reviewer sees
them (and the developer prompt demands a justification).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.pipeline.executor import PipelineExecutor

logger = logging.getLogger(__name__)


def capture_repo_baseline(repo: Path) -> dict:
    """Snapshot the repo before developer agents run (git HEAD or file census)."""
    baseline: dict = {"git_head": None, "file_count": 0, "line_count": 0}
    if (repo / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                baseline["git_head"] = result.stdout.strip()
        except Exception:
            pass
    baseline["file_count"], baseline["line_count"] = _census(repo)
    return baseline


_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
_TEXT_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".html", ".css", ".md", ".yaml", ".yml", ".json", ".txt", ".toml"}


def _census(repo: Path) -> tuple[int, int]:
    files = 0
    lines = 0
    if not repo.is_dir():
        return 0, 0
    for path in repo.rglob("*"):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        files += 1
        if path.suffix in _TEXT_SUFFIXES:
            try:
                lines += sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
            except Exception:
                continue
    return files, lines


def compute_change_stats(repo: Path, baseline: dict) -> dict:
    """Diff stats vs the captured baseline (git when available, census otherwise)."""
    stats: dict = {"files_changed": 0, "lines_changed": 0, "method": "census"}
    head = baseline.get("git_head")
    if head and (repo / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "diff", "--shortstat", head],
                cwd=repo, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                stats["method"] = "git"
                parts = result.stdout.strip()
                # e.g. "8 files changed, 214 insertions(+), 40 deletions(-)"
                import re

                files_match = re.search(r"(\d+) files? changed", parts)
                ins_match = re.search(r"(\d+) insertions?", parts)
                del_match = re.search(r"(\d+) deletions?", parts)
                stats["files_changed"] = int(files_match.group(1)) if files_match else 0
                stats["lines_changed"] = (
                    (int(ins_match.group(1)) if ins_match else 0)
                    + (int(del_match.group(1)) if del_match else 0)
                )
                return stats
        except Exception:
            pass

    files_now, lines_now = _census(repo)
    stats["files_changed"] = abs(files_now - int(baseline.get("file_count") or 0))
    stats["lines_changed"] = abs(lines_now - int(baseline.get("line_count") or 0))
    return stats


async def record_change_stats(
    ex: "PipelineExecutor",
    session,
    project,
    baseline: dict,
    *,
    label: str,
    units: list | None = None,
    context: dict | None = None,
    outputs: str = "",
) -> dict:
    from app.services.evidence import record_evidence

    repo = ex.workspace.repo_dir(project.id)
    stats = compute_change_stats(repo, baseline)
    oversized = (
        stats["files_changed"] > settings.change_budget_files
        or stats["lines_changed"] > settings.change_budget_lines
    )
    stats["oversized"] = oversized
    stats["budget"] = {
        "files": settings.change_budget_files,
        "lines": settings.change_budget_lines,
    }
    stats["label"] = label
    if units:
        stats["units"] = [getattr(u, "title", str(u)) for u in units][:10]

    try:
        await record_evidence(
            session,
            project.id,
            kind="change_stats",
            reference=label,
            passed=not oversized,
            payload=stats,
        )
    except Exception:
        logger.debug("Could not record change stats", exc_info=True)

    if context is not None:
        context["change_stats_oversized"] = context.get("change_stats_oversized") or oversized
        if "JUSTIFICATION:" in (outputs or ""):
            context["change_justification"] = True

    if oversized:
        ex.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[change-budget] {label}: {stats['files_changed']} files / "
            f"{stats['lines_changed']} lines exceeds soft budget "
            f"({settings.change_budget_files} files / {settings.change_budget_lines} lines) "
            "— reviewer will see this",
        )
    return stats
