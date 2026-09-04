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
from app.services.factory_settings import get_agent_backend, get_agent_models
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

_CURSOR_ROLES = {AgentRole.ARCHITECT, AgentRole.DEVELOPER, AgentRole.REVIEWER, AgentRole.ADVERSARY}
# Architect can run on Cursor Cloud without a repo (text artifacts only).
# Reviewer uses the local checklist so it can read factory planning artifacts.
_CLOUD_TEXT_ROLES = {AgentRole.ARCHITECT}


class FactoryAgentRunner(LocalAgentRunner):
    """Routes LLM roles to Cursor; keeps tester/docker/preview on local runner."""

    def __init__(self, workspace: WorkspaceManager | None = None) -> None:
        super().__init__(workspace)
        self._cloud = CursorCloudRunner(self.workspace)
        self._cursor_local = CursorLocalRunner(self.workspace)
        self._cached_backend: str | None = None
        self._cached_models: dict[str, str] | None = None

    async def _resolve_backend(self) -> str:
        if self._cached_backend:
            return self._cached_backend
        async with SessionLocal() as session:
            backend = await get_agent_backend(session)
        self._cached_backend = backend
        return backend

    async def _resolve_model(self, role: AgentRole) -> str:
        if self._cached_models is None:
            async with SessionLocal() as session:
                self._cached_models = await get_agent_models(session)
        return self._cached_models.get(role.value, settings.cursor_agent_model)

    async def _resolve_api_key(self) -> str | None:
        async with SessionLocal() as session:
            return await get_api_key(session)

    def invalidate_settings_cache(self) -> None:
        self._cached_backend = None
        self._cached_models = None

    def _cursor_eligible(self, role: AgentRole, context: dict) -> bool:
        if role in _CURSOR_ROLES:
            return True
        # The tester runs deterministically except when asked to author
        # acceptance tests from the contract (needs an LLM + repo).
        if role == AgentRole.TESTER and context.get("test_stage") == "write_acceptance":
            return True
        return False

    async def run(
        self,
        role: AgentRole,
        project_id: UUID,
        task_id: UUID,
        workspace: str,
        context: dict,
    ) -> AgentRun:
        if not self._cursor_eligible(role, context):
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
        if role == AgentRole.ARCHITECT and context.get("enrichment_pass") and not context.get("repo_url"):
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                "[architect] Enrichment ideation — using factory preview audit (no repo / private preview)",
            )
            return await super().run(role, project_id, task_id, workspace, context)

        if role == AgentRole.ARCHITECT and context.get("repo_exploration"):
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                "[architect] Repository exploration — classifying linked codebase",
            )

        if backend == "cursor_cloud" and not context.get("repo_url"):
            if role == AgentRole.REVIEWER:
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[{role.value}] No repo_url — using local factory checklist (reads planning artifacts)",
                )
                return await super().run(role, project_id, task_id, workspace, context)
            if role in _CLOUD_TEXT_ROLES:
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[{role.value}] No repo_url — using Cursor Cloud without a GitHub repo",
                )
            else:
                effective_backend = "cursor_local"
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    (
                        f"[{role.value}] No repo_url — running Cursor local agent on the workspace. "
                        "Link a GitHub repo to use Cursor Cloud for implementation."
                    ),
                )

        agent_id = f"{effective_backend}-{role.value}-{str(task_id)[:8]}"
        run = AgentRun(task_id=task_id, role=role, agent_id=agent_id)
        model = await self._resolve_model(role)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            f"[{role.value}] Using model {model}",
        )

        on_agent_progress = context.get("on_agent_progress")
        if on_agent_progress:
            await on_agent_progress(
                role.value,
                "starting",
                f"Launching {effective_backend} agent",
                task_id=str(task_id),
            )

        try:
            if effective_backend == "cursor_cloud":
                async with SessionLocal() as session:
                    from app.services.agent_concurrency import wait_for_cursor_capacity

                    budget = await wait_for_cursor_capacity(
                        session, min_slots=1, timeout_seconds=600, poll_seconds=20
                    )
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        f"[concurrency] {budget.strategy}",
                    )
                    if budget.max_parallel < 1:
                        run.success = False
                        run.output = (
                            "No Cursor Cloud agent slots available. "
                            "Archive idle cloud agents or wait for running agents to finish, then retry."
                        )
                        return run

                success, output, cursor_id = await self._cloud.run_role(
                    api_key, role, project_id, task_id, workspace, context, model_id=model
                )
                if cursor_id:
                    run.agent_id = cursor_id
                    run.cursor_url = f"https://cursor.com/agents/{cursor_id}"
            else:
                success, output, cursor_id = await self._cursor_local.run_role(
                    api_key, role, project_id, task_id, workspace, context, model=model
                )
                if cursor_id:
                    run.agent_id = cursor_id
        except Exception as exc:
            logger.exception("Cursor agent failed for %s", role)
            message = f"Cursor failed: {type(exc).__name__}: {exc or 'unknown error'}"
            self.workspace.append_log(project_id, "pipeline.log", f"[{role.value}] {message}")
            run.success = False
            run.output = message
            return run

        if not success:
            if "stopped by user" in output.lower():
                run.success = False
                run.output = output
                return run
            self.workspace.append_log(
                project_id,
                "pipeline.log",
                f"[{role.value}] Cursor unsuccessful: {output[:1500]}",
            )
            run.success = False
            run.output = output or "Cursor agent did not complete successfully"
            return run

        if role == AgentRole.REVIEWER:
            run.success, run.output = await self._finalize_reviewer(project_id, context, output)
        else:
            run.success = True
            run.output = output
        if on_agent_progress:
            await on_agent_progress(
                role.value,
                "finished" if run.success else "failed",
                (run.output or "")[:300],
                agent_id=run.agent_id or None,
                task_id=str(task_id),
                cursor_url=run.cursor_url,
            )
        return run

    async def _finalize_reviewer(
        self, project_id: UUID, context: dict, cursor_output: str
    ) -> tuple[bool, str]:
        """Use the Cursor reviewer's verdict when parseable; local checklist otherwise.

        A Cursor rejection stands — the factory never overrides an LLM
        reviewer's rejection with its own checklist (the checklist is the
        floor, not the ceiling).
        """
        import json

        from app.artifacts.parsing import parse_agent_json
        from app.artifacts.schemas import ReviewReport

        report = parse_agent_json(ReviewReport, cursor_output)
        if report is not None:
            payload = json.dumps(report.model_dump(), indent=2)
            self.workspace.write_artifact(project_id, "review.json", payload)
            if not report.approved:
                self.workspace.append_log(
                    project_id,
                    "pipeline.log",
                    f"[reviewer] Cursor rejected: {', '.join(report.concerns[:5]) or report.severity}",
                )
            return report.approved, payload

        return await super()._reviewer(project_id, context, UUID(int=0), "cursor-reviewer")

    async def stream_events(self, run_id: UUID) -> AsyncIterator[AgentEvent]:
        return
        yield  # pragma: no cover


def create_agent_runner(workspace: WorkspaceManager | None = None) -> FactoryAgentRunner:
    return FactoryAgentRunner(workspace or WorkspaceManager())
