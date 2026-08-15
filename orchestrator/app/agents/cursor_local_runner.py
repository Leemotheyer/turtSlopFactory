"""Run pipeline roles via Cursor local agents (cursor-sdk) against the project workspace."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.agents.prompt_builder import build_role_prompt
from app.config import settings
from app.models import AgentRole
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


def _run_text(run: object) -> str:
    """cursor-sdk Run.text is a method; older handles used a string attribute."""
    text_attr = getattr(run, "text", None)
    if callable(text_attr):
        value = text_attr()
        return str(value or "")
    if text_attr:
        return str(text_attr)
    result = getattr(run, "result", None)
    if result is not None:
        if isinstance(result, str):
            return result
        nested = getattr(result, "text", None)
        if callable(nested):
            return str(nested() or "")
        if nested:
            return str(nested)
    return str(run) if run is not None else ""


class CursorLocalRunner:
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
        model: str | None = None,
    ) -> tuple[bool, str, str]:
        prompt = build_role_prompt(role, context)
        agent_id = f"cursor-local-{role.value}-{str(task_id)[:8]}"
        selected_model = model or settings.cursor_agent_model

        try:
            from cursor_sdk import Agent, LocalAgentOptions
        except ImportError:
            return (
                False,
                "cursor-sdk is not installed in this factory image. "
                "Rebuild with cursor-sdk, or link a GitHub repo so developers can use Cursor Cloud.",
                agent_id,
            )

        def _execute() -> str:
            with Agent.create(
                model=selected_model,
                api_key=api_key,
                local=LocalAgentOptions(cwd=workspace_path),
            ) as agent:
                run = agent.send(prompt)
                wait = getattr(run, "wait", None)
                if callable(wait):
                    wait()
                return _run_text(run) or "Cursor local agent completed"

        try:
            output = await asyncio.to_thread(_execute)
        except Exception as exc:
            logger.warning("Cursor local agent failed: %s", exc)
            return False, f"Cursor local agent error: {exc}", agent_id

        self._collect_workspace_artifacts(project_id, role, workspace_path, output)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[{role.value}] Cursor local agent finished ({len(output)} chars)",
        )
        return True, output, agent_id

    def _collect_workspace_artifacts(
        self,
        project_id: UUID,
        role: AgentRole,
        workspace_path: str,
        output: str,
    ) -> None:
        """Copy docs the local agent wrote in the repo into factory artifacts/."""
        from pathlib import Path

        repo = Path(workspace_path)
        if role == AgentRole.ARCHITECT:
            for name in ("requirements.md", "architecture.md"):
                path = repo / name
                if path.is_file() and path.stat().st_size > 0:
                    self.workspace.write_artifact(project_id, name, path.read_text(encoding="utf-8"))
            if "requirements.md" not in self.workspace.list_artifacts(project_id) and output.strip():
                self.workspace.write_artifact(project_id, "requirements.md", output)
        elif role == AgentRole.REVIEWER:
            review = repo / "review.json"
            if review.is_file() and review.stat().st_size > 0:
                self.workspace.write_artifact(project_id, "review.json", review.read_text(encoding="utf-8"))
