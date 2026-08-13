"""Factory agent runner: Cursor Cloud (default), Cursor local, or deterministic local."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

from app.agents.base import AgentEvent, AgentRun, AgentRunner
from app.agents.cursor_cloud_runner import CursorCloudRunner
from app.agents.cursor_local_runner import CursorLocalRunner
from app.agents.local_runner import LocalAgentRunner
from app.config import settings
from app.database import SessionLocal
from app.models import AgentRole
from app.services.cursor_connection import get_api_key
from app.services.factory_settings import get_agent_backend
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_CURSOR_ROLES = {AgentRole.ARCHITECT, AgentRole.DEVELOPER, AgentRole.REVIEWER}


class FactoryAgentRunner(LocalAgentRunner):
    """Routes LLM roles to Cursor; keeps tester/docker/preview on local runner."""

    def __init__(self, workspace: WorkspaceManager | None = None) -> None:
        super().__init__(workspace)
        self._cloud = CursorCloudRunner(self.workspace)
        self._cursor_local = CursorLocalRunner(self.workspace)
        self._cached_backend: str | None = None

    async def _resolve_backend(self) -> str:
        if self._cached_backend:
            return self._cached_backend
        async with SessionLocal() as session:
            backend = await get_agent_backend(session)
        self._cached_backend = backend
        return backend

    async def _resolve_api_key(self) -> str | None:
        async with SessionLocal() as session:
            return await get_api_key(session)

    def invalidate_settings_cache(self) -> None:
        self._cached_backend = None

    async def run(
        self,
        role: AgentRole,
        project_id: UUID,
        task_id: UUID,
        workspace: str,
        context: dict,
    ) -> AgentRun:
        if role not in _CURSOR_ROLES:
            return await super().run(role, project_id, task_id, workspace, context)

        backend = await self._resolve_backend()
        if backend == "local":
            return await super().run(role, project_id, task_id, workspace, context)

        api_key = await self._resolve_api_key()
        if not api_key:
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] No Cursor API key — using local scaffold",
            )
            return await super().run(role, project_id, task_id, workspace, context)

        effective_backend = backend
        if backend == "cursor_cloud" and not context.get("repo_url"):
            effective_backend = "cursor_local"
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] No repo_url — using Cursor local agent on workspace",
            )

        agent_id = f"{effective_backend}-{role.value}-{str(task_id)[:8]}"
        run = AgentRun(task_id=task_id, role=role, agent_id=agent_id)

        try:
            if effective_backend == "cursor_cloud":
                success, output, cursor_id = await self._cloud.run_role(
                    api_key, role, project_id, task_id, workspace, context
                )
                if cursor_id:
                    run.agent_id = cursor_id
            else:
                success, output, cursor_id = await self._cursor_local.run_role(
                    api_key, role, project_id, task_id, workspace, context
                )
                if cursor_id:
                    run.agent_id = cursor_id
        except Exception as exc:
            logger.exception("Cursor agent failed for %s", role)
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor failed ({exc}); falling back to local scaffold",
            )
            return await super().run(role, project_id, task_id, workspace, context)

        if not success:
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor unsuccessful; falling back to local scaffold",
            )
            return await super().run(role, project_id, task_id, workspace, context)

        if role == AgentRole.REVIEWER:
            run.success, run.output = await self._finalize_reviewer(project_id, context, output)
        else:
            run.success = True
            run.output = output
        return run

    async def _finalize_reviewer(
        self, project_id: UUID, context: dict, cursor_output: str
    ) -> tuple[bool, str]:
        artifacts = self.workspace.list_artifacts(project_id)
        if "review.json" in artifacts:
            import json

            raw = self.workspace.read_artifact(project_id, "review.json")
            if raw:
                try:
                    report = json.loads(raw)
                    approved = report.get("decision") == "approve"
                    return approved, json.dumps(report, indent=2)
                except json.JSONDecodeError:
                    pass
        return await super()._reviewer(project_id, context, UUID(int=0), "cursor-reviewer")

    async def stream_events(self, run_id: UUID) -> AsyncIterator[AgentEvent]:
        return
        yield  # pragma: no cover


def create_agent_runner(workspace: WorkspaceManager | None = None) -> FactoryAgentRunner:
    return FactoryAgentRunner(workspace or WorkspaceManager())
