"""Run pipeline roles via Cursor local agents (cursor-sdk)."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.agents.prompt_builder import build_role_prompt
from app.config import settings
from app.models import AgentRole
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


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
    ) -> tuple[bool, str, str]:
        prompt = build_role_prompt(role, context)
        agent_id = f"cursor-local-{role.value}-{str(task_id)[:8]}"

        try:
            from cursor_sdk import Agent, LocalAgentOptions
        except ImportError:
            return False, "cursor-sdk not installed; pip install cursor-sdk", agent_id

        def _execute() -> str:
            with Agent.create(
                model=settings.cursor_agent_model,
                api_key=api_key,
                local=LocalAgentOptions(cwd=workspace_path),
            ) as agent:
                run = agent.send(prompt)
                if hasattr(run, "wait"):
                    run.wait()
                text = getattr(run, "text", None) or str(run)
                return text or "Cursor local agent completed"

        try:
            output = await asyncio.to_thread(_execute)
        except Exception as exc:
            logger.warning("Cursor local agent failed: %s", exc)
            return False, f"Cursor local agent error: {exc}", agent_id

        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[{role.value}] Cursor local agent finished ({len(output)} chars)",
        )
        return True, output, agent_id
