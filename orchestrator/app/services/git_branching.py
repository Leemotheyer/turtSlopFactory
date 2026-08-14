"""Isolated factory branches — develop off main, merge only with approval."""

from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.db_models import ProjectRow
from app.services.github_connection import _explain_push_denial, verify_repo_push_access
from app.workspace.manager import WorkspaceManager
from app.workspace.provisioner import normalize_repo_url, provision_repo

_BRANCH_SLUG = re.compile(r"[^a-z0-9]+")
_UNSET = object()


def _is_invalid_work_branch(work_branch: str | None) -> bool:
    """Detect branches created before the project id was assigned."""
    return bool(work_branch and work_branch.rsplit("-", 1)[-1].lower() == "none")


@dataclass
class BranchPlan:
    base_branch: str
    work_branch: str | None
    active_branch: str
    isolated: bool


def generate_work_branch(project_name: str, project_id: UUID) -> str:
    slug = _BRANCH_SLUG.sub("-", project_name.lower().strip())[:24].strip("-") or "project"
    return f"factory/{slug}-{str(project_id)[:8]}"


def resolve_branch_plan(row: ProjectRow) -> BranchPlan:
    base = (row.base_branch or "main").strip() or "main"
    isolated = bool(row.isolate_branch and row.repo_url)
    if not isolated:
        active = (row.branch or base).strip() or base
        return BranchPlan(base_branch=base, work_branch=None, active_branch=active, isolated=False)

    work = (row.work_branch or generate_work_branch(row.name, row.id)).strip()
    return BranchPlan(base_branch=base, work_branch=work, active_branch=work, isolated=True)


def _auth_repo_url(repo_url: str, token: str | None) -> str:
    if not token:
        return repo_url
    normalized = normalize_repo_url(repo_url) or repo_url
    return normalized.replace("https://", f"https://x-access-token:{token}@", 1)


def _run_git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


async def ensure_work_branch(
    workspace: WorkspaceManager,
    project_id: UUID,
    repo_url: str,
    base_branch: str,
    work_branch: str,
    *,
    github_token: str | None = None,
    force_reclone: bool = False,
) -> str:
    """Clone base branch locally and check out the factory work branch."""
    if force_reclone:
        await provision_repo(workspace, project_id, repo_url, base_branch, force=True)
    else:
        await provision_repo(workspace, project_id, repo_url, base_branch)

    repo_path = workspace.repo_dir(project_id)
    auth_url = _auth_repo_url(repo_url, github_token)

    push_warning: str | None = None
    if github_token:
        push_check = await verify_repo_push_access(github_token, repo_url)
        if not push_check.get("can_push"):
            push_warning = str(push_check.get("message"))

    def _run() -> str:
        if not (repo_path / ".git").exists():
            return "Repository not initialized in workspace"

        _run_git(repo_path, "remote", "set-url", "origin", auth_url)
        _run_git(repo_path, "fetch", "origin", base_branch, "--depth", "1")
        _run_git(repo_path, "fetch", "origin", work_branch, "--depth", "1")

        if _run_git(repo_path, "rev-parse", "--verify", work_branch).returncode == 0:
            checkout = _run_git(repo_path, "checkout", work_branch)
            if checkout.returncode != 0:
                checkout = _run_git(repo_path, "checkout", "-b", work_branch, f"origin/{work_branch}")
        elif _run_git(repo_path, "rev-parse", "--verify", f"origin/{work_branch}").returncode == 0:
            checkout = _run_git(repo_path, "checkout", "-b", work_branch, f"origin/{work_branch}")
        else:
            _run_git(repo_path, "checkout", base_branch)
            checkout = _run_git(repo_path, "checkout", "-b", work_branch)

        if checkout.returncode != 0:
            return f"Could not check out work branch {work_branch}: {checkout.stderr[:400]}"

        if push_warning:
            return f"Checked out {work_branch} locally; {push_warning}"

        push = _run_git(repo_path, "push", "-u", "origin", work_branch)
        if push.returncode == 0:
            return f"Working on factory branch {work_branch} (based on {base_branch})"
        if github_token:
            return f"Checked out {work_branch} locally; {_explain_push_denial(push.stderr, repo_url)}"
        return (
            f"Checked out {work_branch} locally. Add GITHUB_TOKEN secret to push the branch to GitHub."
        )

    return await asyncio.to_thread(_run)


async def merge_work_branch_to_base(
    workspace: WorkspaceManager,
    project_id: UUID,
    repo_url: str,
    base_branch: str,
    work_branch: str,
    *,
    github_token: str | None = None,
) -> tuple[bool, str]:
    repo_path = workspace.repo_dir(project_id)
    auth_url = _auth_repo_url(repo_url, github_token)

    def _run() -> tuple[bool, str]:
        if not (repo_path / ".git").exists():
            return False, "No git repository in workspace"

        _run_git(repo_path, "remote", "set-url", "origin", auth_url)
        fetch_work = _run_git(repo_path, "fetch", "origin", work_branch)
        fetch_base = _run_git(repo_path, "fetch", "origin", base_branch)
        if fetch_work.returncode != 0:
            return False, f"Could not fetch {work_branch}: {fetch_work.stderr[:300]}"
        if fetch_base.returncode != 0:
            return False, f"Could not fetch {base_branch}: {fetch_base.stderr[:300]}"

        checkout = _run_git(repo_path, "checkout", base_branch)
        if checkout.returncode != 0:
            checkout = _run_git(repo_path, "checkout", "-b", base_branch, f"origin/{base_branch}")
        if checkout.returncode != 0:
            return False, f"Could not check out {base_branch}: {checkout.stderr[:300]}"

        pull = _run_git(repo_path, "pull", "origin", base_branch)
        if pull.returncode != 0:
            return False, f"Could not update {base_branch}: {pull.stderr[:300]}"

        merge = _run_git(repo_path, "merge", "--no-ff", f"origin/{work_branch}", "-m", f"Merge {work_branch} into {base_branch}")
        if merge.returncode != 0:
            return False, f"Merge failed: {merge.stderr[:400]}"

        if not github_token:
            return True, f"Merged {work_branch} into {base_branch} locally. Add GITHUB_TOKEN to push to GitHub."

        push = _run_git(repo_path, "push", "origin", base_branch)
        if push.returncode != 0:
            return False, f"Merged locally but push failed: {push.stderr[:400]}"
        return True, f"Merged {work_branch} into {base_branch} and pushed to GitHub"

    return await asyncio.to_thread(_run)


def apply_isolated_branch_fields(
    row: ProjectRow,
    *,
    repo_url: str | None | object = _UNSET,
    base_branch: str | None = None,
    branch: str | None = None,
    work_branch: str | None = None,
    isolate_branch: bool | None = None,
) -> None:
    """Normalize branch fields on a project row after create/update."""
    if repo_url is not _UNSET:
        row.repo_url = repo_url  # type: ignore[assignment]

    if base_branch is not None:
        row.base_branch = (base_branch.strip() or "main")

    if isolate_branch is not None:
        row.isolate_branch = isolate_branch

    if work_branch is not None:
        row.work_branch = work_branch.strip() or None

    if branch is not None and not row.isolate_branch:
        row.branch = (branch.strip() or row.base_branch or "main")

    if not row.repo_url:
        row.isolate_branch = False
        row.work_branch = None
        row.merge_status = None
        return

    if row.isolate_branch:
        base = (row.base_branch or "main").strip() or "main"
        row.base_branch = base
        if not row.work_branch or _is_invalid_work_branch(row.work_branch):
            if row.id is None:
                raise ValueError("Project id is required before generating a work branch")
            row.work_branch = generate_work_branch(row.name, row.id)
        row.branch = row.work_branch
        if row.merge_status is None:
            row.merge_status = "pending"
    else:
        active = (row.base_branch or row.branch or "main").strip() or "main"
        row.branch = active
        row.base_branch = active
        row.work_branch = None
        row.merge_status = None


async def setup_project_branches(
    workspace: WorkspaceManager,
    row: ProjectRow,
    *,
    github_token: str | None = None,
    force_reclone: bool = False,
) -> str:
    """Provision workspace and ensure the correct branch is checked out."""
    if not row.repo_url:
        return "No repository linked"

    plan = resolve_branch_plan(row)
    if plan.isolated and plan.work_branch:
        message = await ensure_work_branch(
            workspace,
            row.id,
            row.repo_url,
            plan.base_branch,
            plan.work_branch,
            github_token=github_token,
            force_reclone=force_reclone,
        )
        row.branch = plan.work_branch
        row.work_branch = plan.work_branch
        row.base_branch = plan.base_branch
        return message

    message = await provision_repo(
        workspace,
        row.id,
        row.repo_url,
        plan.active_branch,
        force=force_reclone,
    )
    row.branch = plan.active_branch
    return message
