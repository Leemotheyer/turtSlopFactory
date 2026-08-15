"""Run pipeline roles via Cursor Cloud Agents API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from uuid import UUID

import httpx

from app.agents.prompt_builder import build_role_prompt
from app.config import settings
from app.models import AgentRole
from app.services.cursor_client import (
    CursorApiError,
    CursorClient,
    is_cursor_capacity_error,
    is_cursor_model_error,
)
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_TERMINAL_OK = {"FINISHED", "COMPLETED"}
_TEXT_ROLES = {AgentRole.ARCHITECT, AgentRole.REVIEWER}


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


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
        mode = (
            "agent"
            if context.get("enrichment_pass")
            else ("plan" if role == AgentRole.ARCHITECT else "agent")
        )

        repos: list[dict[str, str]] | None = None
        if repo_url:
            repos = [{"url": repo_url, "startingRef": branch}]

        from app.services.agent_concurrency import (
            invalidate_active_agent_cache,
            reclaim_idle_factory_agents,
        )

        try:
            archived = await reclaim_idle_factory_agents(api_key)
        except Exception as exc:
            logger.warning("Could not reclaim idle factory agents: %s", exc)
            archived = 0
        if archived:
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[concurrency] Archived {archived} idle factory cloud agent(s) to free account slots",
            )

        async with CursorClient(api_key) as client:
            created, create_error = await _create_agent_with_retries(
                client,
                api_key,
                prompt,
                name=agent_name,
                repos=repos,
                model_id=selected_model,
                mode=mode,
            )
            if created is None:
                return False, create_error, ""

            agent_id, run_id, agent = _parse_created_agent(created)
            if agent_id and not run_id:
                try:
                    detail = await client.get_agent(agent_id)
                    _, run_id, extra = _parse_created_agent(detail)
                    if extra.get("url"):
                        agent["url"] = extra["url"]
                    if not run_id:
                        run_id = str(detail.get("latestRunId") or "")
                except CursorApiError as exc:
                    return False, f"Cursor cloud create failed: {exc.message}", agent_id
            if not agent_id or not run_id:
                return False, "Cursor cloud response missing agent/run id", agent_id

            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor cloud agent {agent_id} run {run_id}",
            )
            invalidate_active_agent_cache()

            agent_url = agent.get("url") or f"https://cursor.com/agents/{agent_id}"
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor cloud agent {agent_id} — {agent_url}",
            )

            should_stop = context.get("should_stop")
            on_agent_progress = context.get("on_agent_progress")

            async def _emit_progress(status: str, run_payload: dict) -> None:
                if not on_agent_progress:
                    return
                detail = (run_payload.get("statusMessage") or run_payload.get("message") or "")[:500]
                await on_agent_progress(
                    role.value,
                    status.lower(),
                    detail,
                    agent_id=agent_id,
                    task_id=str(task_id),
                    cursor_url=agent_url,
                )

            def _sync_progress(status: str, run_payload: dict) -> None:
                if not on_agent_progress:
                    return
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_emit_progress(status, run_payload))
                except RuntimeError:
                    pass

            try:
                final_run = await client.wait_for_run(
                    agent_id,
                    run_id,
                    poll_seconds=settings.cursor_cloud_poll_seconds,
                    timeout_seconds=settings.cursor_cloud_timeout_seconds,
                    should_stop=should_stop,
                    on_progress=_sync_progress if on_agent_progress else None,
                )
            except TimeoutError as exc:
                return False, str(exc), agent_id

            status = (final_run.get("status") or "").upper()
            if status == "CANCELLED":
                return False, "Stopped by user", agent_id
            text = _run_result_text(final_run)

            if repos and repo_url:
                synced = await self._sync_repo_from_cloud(
                    project_id, workspace_path, repo_url, final_run
                )
                if synced:
                    text = (text + "\n" + synced).strip()

            self._write_artifacts_from_response(project_id, role, text, context)

            has_docs = _architect_docs_ready(self.workspace, project_id, role, context)
            if status not in _TERMINAL_OK:
                err = _as_dict(final_run.get("result")).get("error") or final_run.get("error") or status
                if role in _TEXT_ROLES and (text.strip() or has_docs):
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        f"[{role.value}] Cloud run ended {status}; using reply text anyway",
                    )
                else:
                    return False, f"Cursor cloud run {status}: {err}", agent_id

            if role == AgentRole.ARCHITECT and not repos and not has_docs:
                if context.get("enrichment_pass"):
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        "[architect] Cloud reply missing enrichment-plan.json — factory will use audit fallback",
                    )
                elif text.strip():
                    self.workspace.write_artifact(project_id, "requirements.md", text)
                    has_docs = True
                else:
                    return (
                        False,
                        "Cursor cloud architect finished without requirements.md / architecture.md in the reply.",
                        agent_id,
                    )

            agent_url = agent.get("url") or f"https://cursor.com/agents/{agent_id}"
            output = text or f"Cursor cloud agent completed ({agent_url})"
            return True, output, agent_id

    def _write_artifacts_from_response(
        self, project_id: UUID, role: AgentRole, text: str, context: dict | None = None
    ) -> None:
        if not text:
            return
        context = context or {}
        if role == AgentRole.ARCHITECT and context.get("enrichment_pass"):
            plan_json = _extract_json_block(text)
            if plan_json:
                self.workspace.write_artifact(project_id, "enrichment-plan.json", plan_json)
                return
            repo_plan = Path(self.workspace.repo_dir(project_id)) / "enrichment-plan.json"
            if repo_plan.is_file():
                return
            return
        if role == AgentRole.ARCHITECT:
            req, arch = _split_requirements_architecture(text)
            if req:
                self.workspace.write_artifact(project_id, "requirements.md", req)
            if arch:
                self.workspace.write_artifact(project_id, "architecture.md", arch)
            if not req and not arch:
                self.workspace.write_artifact(project_id, "requirements.md", text)
            if "architecture.md" not in self.workspace.list_artifacts(project_id):
                fallback_arch = arch or (
                    "# Architecture\n\n"
                    "Derived from requirements.md — FastAPI service with static UI and Docker packaging.\n"
                )
                self.workspace.write_artifact(project_id, "architecture.md", fallback_arch)
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
        git_info = _as_dict(final_run.get("git")) or _as_dict(_as_dict(final_run.get("result")).get("git"))
        branches = git_info.get("branches") or []
        if not branches:
            return "Cloud agent finished; no pushed branch to sync locally."

        first = branches[0]
        if isinstance(first, dict):
            branch = first.get("branch")
        else:
            branch = str(first)
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


def _parse_created_agent(created: dict) -> tuple[str, str, dict]:
    agent = _as_dict(created.get("agent"))
    if not agent and created.get("id"):
        agent = created
    run = _as_dict(created.get("run"))
    agent_id = str(agent.get("id") or created.get("id") or "")
    run_id = str(run.get("id") or agent.get("latestRunId") or created.get("latestRunId") or "")
    return agent_id, run_id, agent


def _run_result_text(final_run: dict) -> str:
    result = final_run.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        nested = result.get("text") or result.get("result") or result.get("message") or ""
        if nested:
            return str(nested).strip()
    text = final_run.get("text")
    if text:
        return str(text).strip()
    return ""


def _architect_docs_ready(
    workspace: WorkspaceManager, project_id: UUID, role: AgentRole, context: dict | None = None
) -> bool:
    if role != AgentRole.ARCHITECT:
        return True
    context = context or {}
    if context.get("enrichment_pass"):
        artifacts = workspace.list_artifacts(project_id)
        if "enrichment-plan.json" in artifacts:
            return True
        repo_plan = workspace.repo_dir(project_id) / "enrichment-plan.json"
        return repo_plan.is_file()
    artifacts = workspace.list_artifacts(project_id)
    return "requirements.md" in artifacts


async def _create_agent_with_retries(
    client: CursorClient,
    api_key: str,
    prompt: str,
    *,
    name: str,
    repos: list[dict[str, str]] | None,
    model_id: str | None,
    mode: str,
) -> tuple[dict | None, str]:
    from app.services.agent_concurrency import invalidate_active_agent_cache, reclaim_idle_factory_agents

    current_model = model_id
    for attempt in range(3):
        try:
            created = await client.create_agent(
                prompt,
                name=name,
                repos=repos,
                model_id=current_model,
                mode=mode,
            )
            return created, ""
        except CursorApiError as exc:
            if is_cursor_capacity_error(exc) and attempt == 0:
                invalidate_active_agent_cache()
                try:
                    await reclaim_idle_factory_agents(api_key, keep_recent=0)
                except Exception:
                    logger.warning("Retry reclaim after capacity error failed", exc_info=True)
                continue
            if is_cursor_model_error(exc) and current_model and attempt < 2:
                logger.warning("Cursor rejected model %s (%s); retrying with account default", current_model, exc.message)
                current_model = None
                continue
            if is_cursor_capacity_error(exc):
                invalidate_active_agent_cache()
                return None, f"Cursor cloud capacity unavailable: {exc.message}"
            return None, f"Cursor cloud create failed: {exc.message}"
        except httpx.TimeoutException as exc:
            logger.warning(
                "Cursor cloud create timed out (attempt %s/3): %s",
                attempt + 1,
                exc,
            )
            if attempt < 2:
                invalidate_active_agent_cache()
                continue
            return None, f"Cursor cloud create timed out after retries: {exc}"
    return None, "Cursor cloud create failed after retries"


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
