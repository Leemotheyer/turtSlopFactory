"""Clone or sync a linked GitHub repository into the project workspace."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from uuid import UUID

from app.workspace.manager import WorkspaceManager

_GITHUB_HTTPS = re.compile(
    r"^https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?$",
    re.I,
)


def normalize_repo_url(url: str | None) -> str | None:
    if not url:
        return None
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if not _GITHUB_HTTPS.match(cleaned):
        raise ValueError("Repository URL must be a GitHub HTTPS URL (https://github.com/owner/repo)")
    return cleaned


def repo_display_name(url: str) -> str:
    cleaned = normalize_repo_url(url) or url
    return cleaned.removeprefix("https://github.com/")


async def provision_repo(
    workspace: WorkspaceManager,
    project_id: UUID,
    repo_url: str,
    branch: str = "main",
    *,
    force: bool = False,
) -> str:
    """Clone or update the linked repository in the project workspace."""
    normalized = normalize_repo_url(repo_url)
    if not normalized:
        return "No repository URL configured"

    branch = (branch or "main").strip() or "main"
    repo_path = workspace.repo_dir(project_id)

    def _run() -> str:
        if force and repo_path.exists():
            import shutil

            shutil.rmtree(repo_path)
            repo_path.mkdir(parents=True, exist_ok=True)

        if (repo_path / ".git").exists():
            for cmd in (
                ["git", "remote", "set-url", "origin", normalized],
                ["git", "fetch", "origin", branch, "--depth", "1"],
                ["git", "checkout", branch],
                ["git", "pull", "origin", branch, "--depth", "1"],
            ):
                result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
                if result.returncode != 0 and cmd[1] != "pull":
                    return f"Git sync failed ({' '.join(cmd[1:])}): {result.stderr[:400]}"
            return f"Synced {repo_display_name(normalized)} @ {branch}"

        repo_path.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--branch", branch, "--depth", "1", normalized, str(repo_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Empty or brand-new repos may not have the default branch yet — try without branch.
            if repo_path.exists():
                import shutil

                shutil.rmtree(repo_path)
            fallback = subprocess.run(
                ["git", "clone", "--depth", "1", normalized, str(repo_path)],
                capture_output=True,
                text=True,
            )
            if fallback.returncode != 0:
                return (
                    f"Could not clone {repo_display_name(normalized)}: "
                    f"{(result.stderr or result.stdout or fallback.stderr)[:400]}"
                )
            return f"Cloned {repo_display_name(normalized)} (default branch)"
        return f"Cloned {repo_display_name(normalized)} @ {branch}"

    return await asyncio.to_thread(_run)
