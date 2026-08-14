"""Run pipeline roles via Cursor Cloud Agents API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from uuid import UUID

from app.agents.prompt_builder import build_role_prompt
from app.config import settings
from app.models import AgentRole
from app.services.cursor_client import CursorApiError, CursorClient
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_TERMINAL_OK = {"FINISHED"}


class CursorCloudRunner:
    def __init__(self, workspace: WorkspaceManager) -> None:
        self.workspace = workspace

    async def run_role(
        self,
        api_key: str,
        role: AgentRole,
        project_id: UUID,
        task_id: UUID,
        workspace_path: str,
        context: dict,
        *,
        model_id: str | None = None,
    ) -> tuple[bool, str, str]:
        """Returns (success, output, agent_id)."""
        prompt = build_role_prompt(role, context)
        repo_url = context.get("repo_url")
        branch = context.get("branch", "main")
        agent_name = f"factory-{role.value}-{str(task_id)[:8]}"
        selected_model = model_id or settings.cursor_agent_model

        repos: list[dict[str, str]] | None = None
        if repo_url:
            repos = [{"url": repo_url, "startingRef": branch}]

        async with CursorClient(api_key) as client:
            try:
                created = await client.create_agent(
                    prompt,
                    name=agent_name,
                    repos=repos,
                    model_id=selected_model,
                )
            except CursorApiError as exc:
                return False, f"Cursor cloud create failed: {exc.message}", ""

            agent = created.get("agent") or {}
            run = created.get("run") or {}
            agent_id = agent.get("id") or ""
            run_id = run.get("id") or agent.get("latestRunId") or ""
            if not agent_id or not run_id:
                return False, "Cursor cloud response missing agent/run id", ""

            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor cloud agent {agent_id} run {run_id}",
            )

            try:
                final_run = await client.wait_for_run(
                    agent_id,
                    run_id,
                    poll_seconds=settings.cursor_cloud_poll_seconds,
                    timeout_seconds=settings.cursor_cloud_timeout_seconds,
                )
            except TimeoutError as exc:
                return False, str(exc), agent_id

            status = (final_run.get("status") or "").upper()
            result = final_run.get("result") or {}
            text = result.get("text") or final_run.get("text") or ""

            if status not in _TERMINAL_OK:
                err = result.get("error") or final_run.get("error") or status
                return False, f"Cursor cloud run {status}: {err}", agent_id

            if repos and repo_url:
                synced = await self._sync_repo_from_cloud(
                    project_id, workspace_path, repo_url, final_run
                )
                if synced:
                    text = (text + "\n" + synced).strip()

            if not repos:
                self._write_artifacts_from_response(project_id, role, text)

            agent_url = agent.get("url") or f"https://cursor.com/agents/{agent_id}"
            output = text or f"Cursor cloud agent completed ({agent_url})"
            return True, output, agent_id

    def _write_artifacts_from_response(self, project_id: UUID, role: AgentRole, text: str) -> None:
        if not text:
            return
        if role == AgentRole.ARCHITECT:
            req, arch = _split_requirements_architecture(text)
            if req:
                self.workspace.write_artifact(project_id, "requirements.md", req)
            if arch:
                self.workspace.write_artifact(project_id, "architecture.md", arch)
            if not req and not arch:
                self.workspace.write_artifact(project_id, "requirements.md", text)
        elif role == AgentRole.REVIEWER:
            review_json = _extract_json_block(text)
            if review_json:
                self.workspace.write_artifact(project_id, "review.json", review_json)

    async def _sync_repo_from_cloud(
        self,
        project_id: UUID,
        workspace_path: str,
        repo_url: str,
        final_run: dict,
    ) -> str:
        git_info = final_run.get("git") or (final_run.get("result") or {}).get("git") or {}
        branches = git_info.get("branches") or []
        if not branches:
            return "Cloud agent finished; no pushed branch to sync locally."

        branch = branches[0].get("branch")
        if not branch:
            return ""

        repo_path = Path(workspace_path)
        repo_path.mkdir(parents=True, exist_ok=True)

        def _clone_or_pull() -> str:
            if (repo_path / ".git").exists():
                subprocess.run(
                    ["git", "fetch", "origin", branch],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                )
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                )
                subprocess.run(
                    ["git", "pull", "origin", branch],
                    cwd=repo_path,
                    capture_output=True,
                    check=False,
                )
                return f"Synced local workspace from branch {branch}"
            result = subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1", repo_url, str(repo_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return f"Could not clone {branch}: {result.stderr[:500]}"
            return f"Cloned {repo_url} @ {branch} into workspace"

        return await asyncio.to_thread(_clone_or_pull)


def _split_requirements_architecture(text: str) -> tuple[str, str]:
    req_match = re.search(
        r"(#+\s*requirements[^\n]*\n.*?)(?=#+\s*architecture|\Z)",
        text,
        re.I | re.S,
    )
    arch_match = re.search(r"(#+\s*architecture[^\n]*\n.*)", text, re.I | re.S)
    req = req_match.group(1).strip() if req_match else ""
    arch = arch_match.group(1).strip() if arch_match else ""
    return req, arch


def _extract_json_block(text: str) -> str | None:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass
    return None
