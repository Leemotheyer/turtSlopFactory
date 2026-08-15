import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.factory import create_agent_runner
from app.config import settings
from app.database import SessionLocal
from app.db_models import DeploymentRow, EventRow, ProjectRow, TaskRow
from app.events import event_bus
from app.models import AgentRole, EventType, FactoryEvent, NotificationType, ProjectState, TaskStatus
from app.services.git_branching import resolve_branch_plan, setup_project_branches
from app.services.discovery import get_discovery
from app.services.input_requests import create_input_request, get_input_responses_for_agents
from app.services.notifications import create_notification
from app.services.notes import get_notes_for_agents
from app.services.progress import record_progress
from app.services.secrets import get_env_status_for_agents, get_github_token, get_secrets_for_runtime, maybe_request_github_token, request_env_var
from app.services.agent_concurrency import (
    concurrency_budget_to_dict,
    resolve_concurrency_budget,
    wait_for_cursor_capacity,
)
from app.services.factory_settings import get_agent_backend, get_preview_origin
from app.services.work_planner import (
    optimize_work_units,
    plan_from_enrichment_features,
    plan_parallel_work,
    work_plan_to_dict,
)
from app.services.product_enrichment import (
    audit_live_preview,
    classify_scope,
    local_enrichment_plan,
    parse_enrichment_plan,
)
from app.state_machine import (
    advance_project,
    block_autonomous,
    fail_project,
    normalize_pipeline_gate,
    pipeline_gate_index,
)
from app.services.preview import (
    build_preview_url,
    preview_from_metadata,
    preview_path,
    preview_upstream,
    update_preview_metadata,
)
from app.services.preview_manager import (
    dev_preview_image_tag,
    preview_container_name,
    start_dev_preview,
    start_docker_preview,
    stop_preview,
)
from app.services.preview_spec import PreviewLaunch, load_preview_spec
from app.workspace.manager import WorkspaceManager
from app.workspace.scaffolder import ensure_dockerfile, scaffold_base

logger = logging.getLogger(__name__)

# Substages while the project state remains IMPLEMENTING or SMOKE_TESTING.
_STAGE_IMPLEMENTING = "implementing"
_STAGE_UNIT_TESTING = "unit_testing"
_STAGE_ENRICHMENT = "enrichment"
_STAGE_SMOKE = "smoke"
_STAGE_REVIEW_SUBSTAGE = "review"


class PipelineStopped(Exception):
    """Raised when the user requests a hard stop of the pipeline."""


class PipelineExecutor:
    def __init__(self) -> None:
        self.workspace = WorkspaceManager()
        self.runner = create_agent_runner(self.workspace)
        self._running: set[UUID] = set()
        self._stop_requested: set[UUID] = set()
        self._pipeline_tasks: dict[UUID, asyncio.Task] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def is_running(self, project_id: UUID) -> bool:
        return project_id in self._running

    def is_stop_requested(self, project_id: UUID) -> bool:
        return project_id in self._stop_requested

    def register_task(self, project_id: UUID, task: asyncio.Task) -> None:
        self._pipeline_tasks[project_id] = task

        def _clear(_task: asyncio.Task) -> None:
            self._pipeline_tasks.pop(project_id, None)

        task.add_done_callback(_clear)

    def request_stop(self, project_id: UUID) -> bool:
        if project_id not in self._running:
            return False
        self._stop_requested.add(project_id)
        task = self._pipeline_tasks.get(project_id)
        if task and not task.done():
            task.cancel()
        return True

    def _check_stop(self, project_id: UUID) -> None:
        if project_id in self._stop_requested:
            raise PipelineStopped()

    def _lock_for(self, project_id: UUID) -> asyncio.Lock:
        if project_id not in self._locks:
            self._locks[project_id] = asyncio.Lock()
        return self._locks[project_id]

    def _load_failed_gate(self, project_id: UUID, context: dict) -> ProjectState | None:
        raw = context.get("failed_gate")
        substage = context.get("failed_substage")
        meta = self.workspace.load_metadata(project_id)
        if not raw:
            raw = meta.get("failed_gate")
        if not substage:
            substage = meta.get("failed_substage")
        if substage:
            context["failed_substage"] = substage
        if not raw:
            return None
        try:
            return ProjectState(raw)
        except ValueError:
            return None

    def _save_failed_gate(
        self,
        project_id: UUID,
        gate: ProjectState | None,
        substage: str | None = None,
    ) -> None:
        meta = self.workspace.load_metadata(project_id)
        if gate:
            meta["failed_gate"] = gate.value
            if substage:
                meta["failed_substage"] = substage
            else:
                meta.pop("failed_substage", None)
        else:
            meta.pop("failed_gate", None)
            meta.pop("failed_substage", None)
        self.workspace.save_metadata(project_id, meta)

    def _should_skip_stage(
        self,
        *,
        gate: ProjectState,
        substage: str | None,
        context: dict,
    ) -> bool:
        if substage == _STAGE_IMPLEMENTING and context.get("implementation_complete"):
            return True
        return False

    def _stage_is_due(
        self,
        *,
        current_gate: ProjectState,
        expected_gate: ProjectState,
        substage: str | None,
        context: dict,
    ) -> bool:
        if self._should_skip_stage(gate=expected_gate, substage=substage, context=context):
            return False

        current_idx = pipeline_gate_index(current_gate)
        expected_idx = pipeline_gate_index(expected_gate)
        if current_idx is None or expected_idx is None:
            return False

        if current_idx > expected_idx:
            return False
        if current_idx < expected_idx:
            return True
        # Same gate — run substages in order (implementing before unit tests).
        if expected_gate == ProjectState.IMPLEMENTING:
            if substage == _STAGE_UNIT_TESTING:
                return context.get("implementation_complete", False) and not context.get(
                    "unit_testing_complete", False
                )
            if substage == _STAGE_ENRICHMENT:
                return context.get("unit_testing_complete", False) and not context.get(
                    "enrichment_complete", False
                )
            if substage == _STAGE_IMPLEMENTING:
                return not context.get("implementation_complete", False)
            return False
        if expected_gate == ProjectState.SMOKE_TESTING:
            if substage == _STAGE_ENRICHMENT:
                return context.get("smoke_testing_complete", False) and not context.get(
                    "post_smoke_enrichment_complete", False
                )
            if substage == _STAGE_REVIEW_SUBSTAGE:
                return context.get("post_smoke_enrichment_complete", False)
            if substage is None:
                return not context.get("smoke_testing_complete", False)
            return False
        return True

    async def _ensure_repo_scaffold(self, project: ProjectRow, context: dict) -> None:
        repo = self.workspace.repo_dir(project.id)
        if context.get("incremental") or (repo / "requirements.txt").exists():
            return
        lock = context.setdefault("_scaffold_lock", asyncio.Lock())
        async with lock:
            if not (repo / "requirements.txt").exists():
                scaffold_base(repo, project.name, project.description)

    async def _ensure_runnable_app(self, project: ProjectRow) -> None:
        """Guarantee app/main.py and tests exist with valid syntax before preview or pytest."""
        repo = self.workspace.repo_dir(project.id)
        repaired = False

        if not self._app_source_valid(repo):
            scaffold_base(repo, project.name, project.description)
            repaired = True
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                "[scaffold] Repaired broken or missing app/main.py and test harness",
            )
        elif not (repo / "tests" / "test_app.py").exists():
            scaffold_base(repo, project.name, project.description)
            repaired = True
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                "[scaffold] Added missing tests/test_app.py",
            )

        if ensure_dockerfile(repo):
            repaired = True
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                "[scaffold] Added missing Dockerfile so later image builds are automatic",
            )

        if repaired and not self._app_source_valid(repo):
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                "[scaffold] WARNING: app/main.py is still invalid after repair",
            )

    def _app_source_valid(self, repo) -> bool:
        main = repo / "app" / "main.py"
        if not main.is_file():
            return False
        try:
            compile(main.read_text(encoding="utf-8"), str(main), "exec")
        except SyntaxError:
            return False
        return True

    def _persist_last_failure(self, project_id: UUID, context: dict) -> None:
        failure = context.get("last_failure")
        if not failure:
            return
        meta = self.workspace.load_metadata(project_id)
        meta["last_failure"] = str(failure)[:4000]
        self.workspace.save_metadata(project_id, meta)

    async def _stage_fix_from_failure(self, session: AsyncSession, project: ProjectRow, context: dict) -> bool:
        """Run a developer pass to fix the last failing stage before retrying."""
        failure = context.get("last_failure")
        if not failure:
            return True

        await self._ensure_runnable_app(project)
        task = await self.create_task(
            session,
            project.id,
            "Fix failing stage",
            str(failure)[:500],
            AgentRole.DEVELOPER,
        )
        run = await self.runner.run(
            AgentRole.DEVELOPER,
            project.id,
            task.id,
            str(self.workspace.repo_dir(project.id)),
            context,
        )
        await self.complete_task(
            session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
        )
        if not run.success:
            context["last_failure"] = run.output
            self._persist_last_failure(project.id, context)
            return False

        substage = context.get("failed_substage")
        if substage in (_STAGE_UNIT_TESTING, _STAGE_IMPLEMENTING, None):
            preview_ok = await self._deploy_live_preview(
                session,
                project,
                context,
                preview_type="dev",
            )
            return preview_ok or not context.get("last_failure")
        return True

    async def emit(
        self,
        session: AsyncSession,
        event_type: EventType,
        project_id: UUID,
        task_id: UUID | None = None,
        agent_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        await event_bus.publish(
            session,
            FactoryEvent(
                type=event_type,
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                payload=payload or {},
            ),
        )

    async def transition(
        self, session: AsyncSession, project: ProjectRow, new_state: ProjectState, **extra
    ) -> None:
        old = project.state
        project.state = new_state.value
        project.updated_at = datetime.utcnow()
        await session.commit()
        await self.emit(
            session,
            EventType.STATE_TRANSITION,
            project.id,
            payload={"from": old, "to": new_state.value, **extra},
        )

    async def create_task(
        self,
        session: AsyncSession,
        project_id: UUID,
        title: str,
        description: str,
        role: AgentRole,
    ) -> TaskRow:
        row = TaskRow(
            project_id=project_id,
            title=title,
            description=description,
            role=role.value,
            status=TaskStatus.RUNNING.value,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await self.emit(
            session,
            EventType.TASK_STATUS_CHANGED,
            project_id,
            row.id,
            payload={"status": "RUNNING", "title": title, "role": role.value},
        )
        await self.emit(
            session,
            EventType.AGENT_COMMAND_STARTED,
            project_id,
            row.id,
            agent_id=f"{role.value}-{str(row.id)[:8]}",
            payload={
                "role": role.value,
                "title": title,
                "description": description[:500],
            },
        )
        return row

    async def complete_task(
        self,
        session: AsyncSession,
        task: TaskRow,
        success: bool,
        output: str,
        *,
        agent_id: str | None = None,
        cursor_url: str | None = None,
    ) -> None:
        task.status = TaskStatus.COMPLETED.value if success else TaskStatus.FAILED.value
        task.updated_at = datetime.utcnow()
        await session.commit()
        effective_agent_id = agent_id or f"{task.role}-{str(task.id)[:8]}"
        payload: dict = {"success": success, "output": output[:2000]}
        if cursor_url:
            payload["cursor_url"] = cursor_url
        await self.emit(
            session,
            EventType.AGENT_COMMAND_FINISHED,
            task.project_id,
            task.id,
            agent_id=effective_agent_id,
            payload=payload,
        )

    async def _handle_stop(
        self,
        session: AsyncSession,
        project_id: UUID,
        project: ProjectRow,
    ) -> None:
        await self._cancel_running_tasks(session, project_id)
        meta = self.workspace.load_metadata(project_id)
        meta.pop("live_agents", None)
        self.workspace.save_metadata(project_id, meta)
        try:
            await stop_preview(
                project_id,
                ephemeral_image=dev_preview_image_tag(project_id),
            )
        except Exception:
            logger.exception("Failed to stop preview while stopping pipeline for %s", project_id)
        self.workspace.append_log(project_id, "pipeline.log", "[stop] Pipeline stopped by user")
        await self.emit(
            session,
            EventType.PIPELINE_STOPPED,
            project_id,
            payload={"state": project.state, "reason": "user_requested"},
        )

    async def _cancel_running_tasks(self, session: AsyncSession, project_id: UUID) -> None:
        result = await session.execute(
            select(TaskRow).where(
                TaskRow.project_id == project_id,
                TaskRow.status == TaskStatus.RUNNING.value,
            )
        )
        for task in result.scalars():
            task.status = TaskStatus.FAILED.value
            task.updated_at = datetime.utcnow()
            await self.emit(
                session,
                EventType.AGENT_COMMAND_FINISHED,
                project_id,
                task.id,
                agent_id=f"{task.role}-{str(task.id)[:8]}",
                payload={"success": False, "output": "Stopped by user"},
            )
        await session.commit()

    async def _refresh_context(self, session: AsyncSession, project: ProjectRow, context: dict) -> None:
        context["notes"] = await get_notes_for_agents(session, project.id)
        context["input_responses"] = await get_input_responses_for_agents(session, project.id)
        context["project_state"] = project.state
        context["env_status"] = await get_env_status_for_agents(session, project.id)
        context["repo_url"] = project.repo_url
        plan = resolve_branch_plan(project)
        context["branch"] = plan.active_branch
        context["base_branch"] = plan.base_branch
        context["work_branch"] = plan.work_branch
        context["isolate_branch"] = plan.isolated
        origin = await get_preview_origin(session)
        context["preview_origin"] = origin
        repo = self.workspace.repo_dir(project.id)
        context["incremental"] = context.get("fix_attempt", 0) > 0 or (repo / "app" / "main.py").exists()
        meta = self.workspace.load_metadata(project.id)
        preview_url = build_preview_url(project.id, origin=origin)
        context["preview_url"] = meta.get("preview_url") or preview_url
        context["preview_path"] = preview_path(project.id)
        context["preview_status"] = meta.get("preview_status")
        context["preview_upstream"] = preview_upstream(project.id, meta)
        spec = load_preview_spec(repo)
        context["preview_health_path"] = meta.get("preview_health_path") or spec.path
        context["preview_app_port"] = meta.get("preview_app_port") or spec.port
        context["should_stop"] = lambda: self.is_stop_requested(project.id)

    def _bind_agent_progress(self, project_id: UUID) -> object:
        async def on_agent_progress(
            role: str,
            status: str,
            detail: str = "",
            *,
            agent_id: str | None = None,
            task_id: str | None = None,
            cursor_url: str | None = None,
        ) -> None:
            line = f"[agent-progress] [{role}] {status}"
            if detail:
                line += f" — {detail[:200]}"
            self.workspace.append_log(project_id, "pipeline.log", line)
            meta = self.workspace.load_metadata(project_id)
            live = meta.get("live_agents") or {}
            key = agent_id or f"{role}-{task_id or 'active'}"
            live[key] = {
                "role": role,
                "status": status,
                "detail": detail[:1000],
                "agent_id": agent_id,
                "cursor_url": cursor_url,
                "task_id": task_id,
                "updated_at": datetime.utcnow().isoformat(),
            }
            meta["live_agents"] = live
            self.workspace.save_metadata(project_id, meta)
            parsed_task_id = None
            if task_id:
                try:
                    parsed_task_id = UUID(task_id)
                except ValueError:
                    parsed_task_id = None
            async with SessionLocal() as session:
                await self.emit(
                    session,
                    EventType.AGENT_COMMAND_OUTPUT,
                    project_id,
                    parsed_task_id,
                    agent_id=agent_id,
                    payload={
                        "role": role,
                        "status": status,
                        "detail": detail[:2000],
                        **({"cursor_url": cursor_url} if cursor_url else {}),
                    },
                )

        return on_agent_progress

    async def _log_progress(
        self,
        session: AsyncSession,
        project_id: UUID,
        category: str,
        title: str,
        summary: str,
        detail: str | None = None,
    ) -> None:
        await record_progress(session, project_id, category, title, summary, detail)

    async def _deploy_live_preview(
        self,
        session: AsyncSession,
        project: ProjectRow,
        context: dict,
        *,
        preview_type: str,
        image_tag: str | None = None,
        notify: bool = False,
    ) -> bool:
        """Start or replace the factory-owned preview container. Agents never launch this."""
        meta = self.workspace.load_metadata(project.id)
        if preview_type == "dev":
            await self._ensure_runnable_app(project)

        origin = context.get("preview_origin") or await get_preview_origin(session)
        preview_url = build_preview_url(project.id, origin=origin)
        runtime_env = await get_secrets_for_runtime(session, project.id)
        repo = self.workspace.repo_dir(project.id)
        spec = load_preview_spec(repo)

        await stop_preview(
            project.id,
            container_name=meta.get("preview_container"),
            ephemeral_image=meta.get("preview_ephemeral_image"),
        )

        launch = PreviewLaunch(
            success=False,
            message="Preview was not attempted",
            backend="simulated",
            failure_kind="infra",
        )

        if preview_type == "dev":
            if self.runner.docker_available():
                log_path = self.workspace.logs_dir(project.id) / "preview-dev.log"
                launch = await start_dev_preview(
                    project.id,
                    repo,
                    log_path,
                    env_vars=runtime_env,
                )
            else:
                launch = PreviewLaunch(
                    success=False,
                    message="Docker is required for live preview",
                    backend="simulated",
                    failure_kind="infra",
                )
        elif self.runner.docker_available():
            tag = image_tag or project.image_tag or context.get("image_tag", "none")
            if tag == "none":
                launch = PreviewLaunch(
                    success=False,
                    message="No image tag",
                    failure_kind="infra",
                )
            else:
                log_path = self.workspace.logs_dir(project.id) / "preview-staging.log"
                launch = await start_docker_preview(
                    project.id,
                    tag,
                    env_vars=runtime_env,
                    repo_path=repo,
                    log_path=log_path,
                )
        else:
            launch = PreviewLaunch(
                success=True,
                message=f"No Docker — simulated preview at {preview_url}",
                backend="simulated",
            )

        success = launch.success
        output = launch.message
        container_id = launch.container_id
        container_name = launch.container_name or (
            preview_container_name(project.id) if launch.backend == "docker" and success else None
        )
        backend = launch.backend
        context["preview_backend"] = backend if success else None
        context["preview_container"] = container_name
        context["preview_url"] = preview_url
        context["preview_path"] = preview_path(project.id)
        context["preview_health_path"] = spec.path
        context["preview_app_port"] = spec.port

        status = "running" if success else "failed"
        if not success:
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[preview] failed ({launch.failure_kind or 'unknown'}): {output[:1500]}",
            )
            self.workspace.write_log(project.id, "preview-failure.log", output)
        else:
            self.workspace.append_log(project.id, "pipeline.log", f"[preview] {output}")

        update_preview_metadata(
            meta,
            project_id=project.id,
            port=None,
            preview_type=preview_type,
            status=status,
            backend=backend,
            origin=origin,
            host=None,
            container_id=container_id,
            container_name=container_name,
            ephemeral_image=launch.ephemeral_image,
            health_path=spec.path,
            app_port=spec.port,
            failure_kind=launch.failure_kind,
        )
        self.workspace.save_metadata(project.id, meta)
        context["preview_status"] = status
        context["preview_upstream"] = preview_upstream(project.id, meta)

        dep = DeploymentRow(
            project_id=project.id,
            environment="preview" if preview_type == "dev" else "staging",
            image_tag=image_tag or project.image_tag or "dev",
            url=preview_url,
            port=None,
            container_id=container_id,
            status=status,
        )
        session.add(dep)
        await session.commit()

        await self.emit(
            session,
            EventType.DEPLOYMENT_FINISHED,
            project.id,
            payload={
                "environment": preview_type,
                "url": preview_url,
                "success": success,
                "preview_type": preview_type,
                "failure_kind": launch.failure_kind,
            },
        )

        if success:
            await self._log_progress(
                session,
                project.id,
                "deploy",
                "Live preview updated",
                f"Open {preview_url} ({preview_type})",
                output[:200] if output else None,
            )
        elif launch.failure_kind == "app":
            context["last_failure"] = (
                "Factory live preview failed to start the app. "
                "Do NOT run docker, docker compose, or uvicorn — the factory owns the preview container. "
                "Fix the application so it listens on 0.0.0.0:8080 and GET /health returns HTTP 200.\n\n"
                f"{output[:3500]}"
            )
            self._persist_last_failure(project.id, context)

        if notify and success:
            await create_notification(
                session,
                project.id,
                NotificationType.PREVIEW_READY,
                "Live preview ready",
                f"{project.name} is running at {preview_url}. Check it while agents iterate.",
                action="preview",
            )

        return success

    async def run_pipeline(self, project_id: UUID) -> None:
        async with self._lock_for(project_id):
            if project_id in self._running:
                return
            self._running.add(project_id)
            self._stop_requested.discard(project_id)

        stopped = False
        try:
            async with SessionLocal() as session:
                project = await session.get(ProjectRow, project_id)
                if not project:
                    return

                context = {
                    "name": project.name,
                    "description": project.description,
                    "repo_url": project.repo_url,
                    "branch": project.branch,
                    "tests_passed": False,
                    "notes": [],
                }
                context["on_agent_progress"] = self._bind_agent_progress(project_id)
                await self._refresh_context(session, project, context)

                if project.repo_url:
                    setup_msg = await setup_project_branches(
                        self.workspace,
                        project,
                        github_token=await get_github_token(session, project_id),
                    )
                    await session.commit()
                    self.workspace.append_log(project_id, "pipeline.log", f"[setup] {setup_msg}")
                    await maybe_request_github_token(session, project_id, setup_msg)
                    await self._refresh_context(session, project, context)

                discovery = await get_discovery(session, project_id)
                if discovery and discovery.responses:
                    context["intake"] = discovery.responses
                    context["loose_plan"] = discovery.loose_plan

                failed_gate = self._load_failed_gate(project_id, context)
                if failed_gate:
                    context["failed_gate"] = failed_gate.value

                meta = self.workspace.load_metadata(project_id)
                if meta.get("last_failure"):
                    context["last_failure"] = meta["last_failure"]

                if ProjectState(project.state) == ProjectState.AUTONOMOUSLY_BLOCKED:
                    resume_gate = failed_gate or ProjectState.PLANNING
                    await self.transition(
                        session,
                        project,
                        resume_gate,
                        reason="manual_resume",
                    )
                    context.pop("fix_attempt", None)
                    context.pop("implementation_complete", None)
                    failed_substage = context.get("failed_substage") or meta.get("failed_substage")
                    if failed_substage == _STAGE_UNIT_TESTING:
                        await self._ensure_runnable_app(project)
                        await self._stage_fix_from_failure(session, project, context)
                        await self._deploy_live_preview(
                            session,
                            project,
                            context,
                            preview_type="dev",
                        )
                        context["implementation_complete"] = True
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        f"[resume] Unblocked — restarting from {resume_gate.value}",
                    )

                if ProjectState(project.state) == ProjectState.REVIEW:
                    context["feedback_iteration"] = True
                    context.pop("implementation_complete", None)
                    context.pop("unit_testing_complete", None)
                    context.pop("enrichment_complete", None)
                    context.pop("post_smoke_enrichment_complete", None)
                    context.pop("enrichment_passes_completed", None)
                    context.pop("smoke_testing_complete", None)
                    context.pop("fix_attempt", None)
                    context.pop("failed_gate", None)
                    context.pop("failed_substage", None)
                    self._save_failed_gate(project_id, None)
                    await self.transition(
                        session,
                        project,
                        ProjectState.IMPLEMENTING,
                        reason="feedback",
                    )
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        "[feedback] Applying notes and guidance — rebuilding from implementation",
                    )
                    await self._log_progress(
                        session,
                        project_id,
                        "feedback",
                        "Applying feedback",
                        "Re-running implementation with your latest notes and answers",
                    )

                async def request_input(**kwargs):
                    return await create_input_request(session, project_id, **kwargs)

                async def request_env(key_name: str, description: str = "", requested_by: str = "agent"):
                    return await request_env_var(session, project_id, key_name, description, requested_by)

                context["request_input"] = request_input
                context["request_env_var"] = request_env
                meta["pipeline_started_at"] = datetime.utcnow().isoformat()
                self.workspace.save_metadata(project_id, meta)

                stages: list[tuple[ProjectState, str | None, object]] = [
                    (ProjectState.PLANNING, None, self._stage_planning),
                    (ProjectState.IMPLEMENTING, _STAGE_IMPLEMENTING, self._stage_implementing),
                    (ProjectState.IMPLEMENTING, _STAGE_UNIT_TESTING, self._stage_unit_testing),
                    (ProjectState.IMPLEMENTING, _STAGE_ENRICHMENT, self._stage_autonomous_enrichment),
                    (ProjectState.UNIT_TESTING, None, self._stage_integration_testing),
                    (ProjectState.INTEGRATION_TESTING, None, self._stage_docker_build),
                    (ProjectState.DOCKER_BUILD, None, self._stage_staging_deploy),
                    (ProjectState.STAGING_DEPLOY, None, self._stage_smoke_testing),
                    (ProjectState.SMOKE_TESTING, _STAGE_ENRICHMENT, self._stage_post_smoke_enrichment),
                    (ProjectState.SMOKE_TESTING, _STAGE_REVIEW_SUBSTAGE, self._stage_review),
                ]

                for expected_gate, substage, stage_fn in stages:
                    self._check_stop(project_id)
                    await session.refresh(project)
                    current = ProjectState(project.state)

                    if current == ProjectState.AUTONOMOUSLY_BLOCKED:
                        break
                    if current == ProjectState.PRODUCTION:
                        break

                    failed = self._load_failed_gate(project_id, context)
                    current_gate = normalize_pipeline_gate(current, failed)
                    if current_gate is None:
                        logger.warning(
                            "Pipeline stopped for %s: state %s is not runnable",
                            project_id,
                            current.value,
                        )
                        break

                    if not self._stage_is_due(
                        current_gate=current_gate,
                        expected_gate=expected_gate,
                        substage=substage,
                        context=context,
                    ):
                        continue

                    if current_gate != expected_gate:
                        await self.transition(session, project, expected_gate)

                    success = await stage_fn(session, project, context)
                    await self._refresh_context(session, project, context)
                    if not success:
                        await self._handle_failure(
                            session,
                            project,
                            context,
                            failed_at=expected_gate,
                            failed_substage=substage,
                        )
                        break

                    if substage == _STAGE_IMPLEMENTING:
                        context["implementation_complete"] = True
                    self._save_failed_gate(project_id, None)
                    context.pop("failed_gate", None)
                    context.pop("failed_substage", None)

        except PipelineStopped:
            stopped = True
            async with SessionLocal() as session:
                project = await session.get(ProjectRow, project_id)
                if project:
                    await self._handle_stop(session, project_id, project)
        except asyncio.CancelledError:
            if project_id in self._stop_requested:
                stopped = True
                async with SessionLocal() as session:
                    project = await session.get(ProjectRow, project_id)
                    if project:
                        await self._handle_stop(session, project_id, project)
        except Exception:
            if project_id in self._stop_requested:
                stopped = True
                async with SessionLocal() as session:
                    project = await session.get(ProjectRow, project_id)
                    if project:
                        await self._handle_stop(session, project_id, project)
            else:
                logger.exception("Pipeline failed for project %s", project_id)
                async with SessionLocal() as session:
                    project = await session.get(ProjectRow, project_id)
                    if project:
                        await self.transition(
                            session, project, ProjectState.AUTONOMOUSLY_BLOCKED, reason="exception"
                        )
                        await create_notification(
                            session,
                            project.id,
                            NotificationType.PIPELINE_BLOCKED,
                            "Pipeline blocked",
                            f"{project.name} hit an unexpected error and needs review.",
                            action="guidance",
                        )
        finally:
            async with self._lock_for(project_id):
                self._running.discard(project_id)
                self._stop_requested.discard(project_id)
                meta = self.workspace.load_metadata(project_id)
                if not stopped:
                    meta.pop("live_agents", None)
                    self.workspace.save_metadata(project_id, meta)

    async def _handle_failure(
        self,
        session: AsyncSession,
        project: ProjectRow,
        context: dict,
        *,
        failed_at: ProjectState,
        failed_substage: str | None = None,
    ) -> None:
        context["failed_gate"] = failed_at.value
        if failed_substage:
            context["failed_substage"] = failed_substage
        self._save_failed_gate(project.id, failed_at, failed_substage)

        if failed_substage == _STAGE_UNIT_TESTING:
            context.pop("implementation_complete", None)
        elif failed_at == ProjectState.PLANNING:
            context.pop("implementation_complete", None)

        if context.get("last_failure"):
            self._persist_last_failure(project.id, context)

        current = ProjectState(project.state)
        try:
            await self.transition(session, project, fail_project(failed_at))
        except Exception:
            await self.transition(session, project, ProjectState.DIAGNOSING)

        attempt = context.get("fix_attempt", 0) + 1
        context["fix_attempt"] = attempt

        if attempt >= settings.max_fix_attempts:
            await self.transition(session, project, block_autonomous())
            await create_notification(
                session,
                project.id,
                NotificationType.PIPELINE_BLOCKED,
                "Pipeline blocked",
                f"{project.name} needs your attention after {attempt} failed fix attempts.",
                action="guidance",
            )
            return

        await self.transition(session, project, ProjectState.FIXING)
        await self.transition(session, project, failed_at)

        if failed_substage == _STAGE_UNIT_TESTING:
            fixed = await self._stage_fix_from_failure(session, project, context)
            if not fixed:
                await self._handle_failure(
                    session,
                    project,
                    context,
                    failed_at=failed_at,
                    failed_substage=failed_substage,
                )
                return
            context["implementation_complete"] = True

        retry_stages: list[tuple[ProjectState, str | None, object]] = [
            (ProjectState.PLANNING, None, self._stage_planning),
            (ProjectState.IMPLEMENTING, _STAGE_IMPLEMENTING, self._stage_implementing),
            (ProjectState.IMPLEMENTING, _STAGE_UNIT_TESTING, self._stage_unit_testing),
            (ProjectState.IMPLEMENTING, _STAGE_ENRICHMENT, self._stage_autonomous_enrichment),
            (ProjectState.UNIT_TESTING, None, self._stage_integration_testing),
            (ProjectState.INTEGRATION_TESTING, None, self._stage_docker_build),
            (ProjectState.DOCKER_BUILD, None, self._stage_staging_deploy),
            (ProjectState.STAGING_DEPLOY, None, self._stage_smoke_testing),
            (ProjectState.SMOKE_TESTING, _STAGE_ENRICHMENT, self._stage_post_smoke_enrichment),
            (ProjectState.SMOKE_TESTING, _STAGE_REVIEW_SUBSTAGE, self._stage_review),
        ]

        failed_idx = pipeline_gate_index(failed_at) or 0
        for expected_gate, substage, stage_fn in retry_stages:
            if (pipeline_gate_index(expected_gate) or 0) < failed_idx:
                continue
            if substage == _STAGE_UNIT_TESTING and not context.get("implementation_complete"):
                continue
            if substage == _STAGE_IMPLEMENTING and context.get("implementation_complete"):
                continue
            if (
                substage == _STAGE_ENRICHMENT
                and expected_gate == ProjectState.IMPLEMENTING
                and not context.get("unit_testing_complete")
            ):
                continue
            if (
                substage == _STAGE_ENRICHMENT
                and expected_gate == ProjectState.IMPLEMENTING
                and context.get("enrichment_complete")
            ):
                continue
            if (
                substage == _STAGE_ENRICHMENT
                and expected_gate == ProjectState.SMOKE_TESTING
                and not context.get("smoke_testing_complete")
            ):
                continue
            if substage == _STAGE_REVIEW_SUBSTAGE and not context.get(
                "post_smoke_enrichment_complete"
            ):
                continue

            await session.refresh(project)
            if ProjectState(project.state) in (
                ProjectState.AUTONOMOUSLY_BLOCKED,
                ProjectState.PRODUCTION,
            ):
                break

            if ProjectState(project.state) != expected_gate:
                await self.transition(session, project, expected_gate)

            success = await stage_fn(session, project, context)
            await self._refresh_context(session, project, context)
            if not success:
                await self._handle_failure(
                    session,
                    project,
                    context,
                    failed_at=expected_gate,
                    failed_substage=substage,
                )
                break

            if substage == _STAGE_IMPLEMENTING:
                context["implementation_complete"] = True
            self._save_failed_gate(project.id, None)
            context.pop("failed_gate", None)
            context.pop("failed_substage", None)

    def _ensure_planning_artifacts(self, project_id: UUID) -> None:
        """Ensure architect outputs include both requirements and architecture docs."""
        from app.agents.cursor_cloud_runner import _split_requirements_architecture

        artifacts = self.workspace.list_artifacts(project_id)
        if "architecture.md" in artifacts:
            return
        requirements = self.workspace.read_artifact(project_id, "requirements.md") if "requirements.md" in artifacts else None
        if not requirements:
            return
        _, arch = _split_requirements_architecture(requirements)
        if not arch:
            arch = (
                "# Architecture\n\n"
                "See `requirements.md` for the full specification. "
                "This project uses the factory default stack: FastAPI backend, "
                "static web UI, in-memory storage, and Docker deployment.\n"
            )
        self.workspace.write_artifact(project_id, "architecture.md", arch)
        self.workspace.append_log(
            project_id,
            "pipeline.log",
            "[planning] Added missing architecture.md from planning output",
        )

    async def _build_work_plan(self, session, project, context: dict) -> tuple[list, dict]:
        budget = await resolve_concurrency_budget(session)
        raw_units = plan_parallel_work(context.get("notes", []), project.description)
        units = optimize_work_units(raw_units, budget.max_parallel)
        plan = work_plan_to_dict(units, concurrency_budget_to_dict(budget))
        self.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[concurrency] {budget.strategy}",
        )
        return units, plan, budget

    async def _stage_planning(self, session, project, context) -> bool:
        await self._refresh_context(session, project, context)
        task = await self.create_task(
            session, project.id, "Architecture planning", project.description, AgentRole.ARCHITECT
        )
        run = await self.runner.run(
            AgentRole.ARCHITECT, project.id, task.id, str(self.workspace.repo_dir(project.id)), context
        )
        await self.complete_task(
            session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
        )
        if not run.success:
            context["last_failure"] = run.output
            self._persist_last_failure(project.id, context)
            return False
        self._ensure_planning_artifacts(project.id)
        units, plan, budget = await self._build_work_plan(session, project, context)
        self.workspace.write_artifact(
            project.id, "work-plan.json", json.dumps(plan, indent=2)
        )
        context["work_plan"] = plan
        await self._log_progress(
            session,
            project.id,
            "planning",
            "Architecture planned",
            (
                f"Requirements ready — {len(units)} work stream(s), "
                f"up to {budget.max_parallel} parallel agent(s)"
            ),
        )
        await self.transition(session, project, advance_project(ProjectState.PLANNING))
        return True

    async def _run_parallel_developers(
        self, session, project, context: dict
    ) -> tuple[bool, str]:
        units, plan, budget = await self._build_work_plan(session, project, context)
        context["work_plan"] = plan

        backend = await get_agent_backend(session)
        if backend == "cursor_cloud":
            budget = await wait_for_cursor_capacity(
                session, min_slots=1, timeout_seconds=600, poll_seconds=20
            )
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[concurrency] {budget.strategy}",
            )

        if budget.max_parallel < 1:
            return False, (
                "No Cursor Cloud agent slots available for parallel implementation. "
                "Wait for running agents to finish or archive idle cloud agents, then retry."
            )

        await self._ensure_repo_scaffold(project, context)

        task_rows: list[tuple] = []
        for unit in units:
            task = await self.create_task(
                session,
                project.id,
                unit.title,
                unit.description,
                AgentRole.DEVELOPER,
            )
            task_rows.append((unit, task))

        await self.emit(
            session,
            EventType.AGENT_COMMAND_STARTED,
            project.id,
            payload={
                "command": "parallel_implement",
                "streams": [u.stream for u in units],
                "count": len(units),
                "max_parallel": budget.max_parallel,
                "active_cursor_agents": budget.active_cursor_agents,
            },
        )

        semaphore = asyncio.Semaphore(budget.max_parallel)

        async def run_unit(unit, task_row: TaskRow) -> tuple[TaskRow, bool, str, str | None, str | None]:
            async with semaphore:
                unit_context = {
                    **context,
                    "work_stream": unit.stream,
                    "work_description": unit.description,
                    "feature_id": unit.feature_id,
                    "feature_content": unit.feature_content,
                }
                run = await self.runner.run(
                    AgentRole.DEVELOPER,
                    project.id,
                    task_row.id,
                    str(self.workspace.repo_dir(project.id)),
                    unit_context,
                )
                return task_row, run.success, run.output, run.agent_id or None, run.cursor_url

        results = await asyncio.gather(*[run_unit(u, t) for u, t in task_rows])

        outputs: list[str] = []
        all_ok = True
        for task_row, success, output, agent_id, cursor_url in results:
            await self.complete_task(
                session,
                task_row,
                success,
                output,
                agent_id=agent_id,
                cursor_url=cursor_url,
            )
            outputs.append(output)
            if not success:
                all_ok = False

        combined = "; ".join(outputs)
        return all_ok, combined

    async def _run_developer_units(
        self,
        session,
        project,
        context: dict,
        units: list,
        *,
        command: str = "parallel_implement",
    ) -> tuple[bool, str]:
        if not units:
            return True, "No developer tasks"

        budget = await resolve_concurrency_budget(session)
        units = optimize_work_units(units, budget.max_parallel)
        backend = await get_agent_backend(session)
        if backend == "cursor_cloud":
            budget = await wait_for_cursor_capacity(
                session, min_slots=1, timeout_seconds=600, poll_seconds=20
            )
            self.workspace.append_log(project.id, "pipeline.log", f"[concurrency] {budget.strategy}")

        if budget.max_parallel < 1:
            return False, "No Cursor Cloud agent slots available for implementation."

        await self._ensure_repo_scaffold(project, context)
        task_rows: list[tuple] = []
        for unit in units:
            task = await self.create_task(
                session,
                project.id,
                unit.title,
                unit.description,
                AgentRole.DEVELOPER,
            )
            task_rows.append((unit, task))

        await self.emit(
            session,
            EventType.AGENT_COMMAND_STARTED,
            project.id,
            payload={
                "command": command,
                "streams": [u.stream for u in units],
                "count": len(units),
                "max_parallel": budget.max_parallel,
            },
        )

        semaphore = asyncio.Semaphore(budget.max_parallel)

        async def run_unit(unit, task_row: TaskRow) -> tuple[TaskRow, bool, str, str | None, str | None]:
            async with semaphore:
                unit_context = {
                    **context,
                    "work_stream": unit.stream,
                    "work_description": unit.description,
                    "feature_id": unit.feature_id,
                    "feature_content": unit.feature_content,
                    "incremental": True,
                }
                run = await self.runner.run(
                    AgentRole.DEVELOPER,
                    project.id,
                    task_row.id,
                    str(self.workspace.repo_dir(project.id)),
                    unit_context,
                )
                return task_row, run.success, run.output, run.agent_id or None, run.cursor_url

        results = await asyncio.gather(*[run_unit(u, t) for u, t in task_rows])
        outputs: list[str] = []
        all_ok = True
        for task_row, success, output, agent_id, cursor_url in results:
            await self.complete_task(
                session,
                task_row,
                success,
                output,
                agent_id=agent_id,
                cursor_url=cursor_url,
            )
            outputs.append(output)
            if not success:
                all_ok = False
        return all_ok, "; ".join(outputs)

    async def _run_enrichment_passes(
        self,
        session,
        project,
        context: dict,
        *,
        max_passes: int,
        completion_key: str,
        log_prefix: str,
    ) -> bool:
        if context.get(completion_key):
            return True

        await self._refresh_context(session, project, context)
        await self._deploy_live_preview(session, project, context, preview_type="dev", notify=False)

        passes_done = int(context.get("enrichment_passes_completed") or 0)
        context["max_enrichment_passes"] = max_passes
        context["max_features_per_pass"] = settings.max_features_per_enrichment_pass

        while passes_done < max_passes:
            pass_number = passes_done + 1
            context["enrichment_pass"] = pass_number
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[{log_prefix}] Starting enrichment pass {pass_number}/{max_passes}",
            )

            audit = await audit_live_preview(context)
            context["preview_audit"] = audit
            self.workspace.write_artifact(
                project.id,
                f"preview-audit-{log_prefix}-pass-{pass_number}.json",
                json.dumps(audit, indent=2),
            )

            task = await self.create_task(
                session,
                project.id,
                f"Product ideation (pass {pass_number})",
                "Audit the live preview and propose improvements",
                AgentRole.ARCHITECT,
            )
            ideation_context = {
                **context,
                "enrichment_pass": pass_number,
                "incremental": True,
            }
            run = await self.runner.run(
                AgentRole.ARCHITECT,
                project.id,
                task.id,
                str(self.workspace.repo_dir(project.id)),
                ideation_context,
            )
            await self.complete_task(
                session,
                task,
                run.success,
                run.output,
                agent_id=run.agent_id or None,
                cursor_url=run.cursor_url,
            )

            plan_raw = None
            repo_plan = self.workspace.repo_dir(project.id) / "enrichment-plan.json"
            if repo_plan.is_file():
                plan_raw = repo_plan.read_text(encoding="utf-8")
            elif "enrichment-plan.json" in self.workspace.list_artifacts(project.id):
                plan_raw = self.workspace.read_artifact(project.id, "enrichment-plan.json")
            plan = parse_enrichment_plan(plan_raw or run.output)
            if not plan.get("features"):
                plan = local_enrichment_plan(audit, pass_number, context.get("notes", []))
                self.workspace.write_artifact(
                    project.id,
                    "enrichment-plan.json",
                    json.dumps(plan, indent=2),
                )

            request_input = context.get("request_input")
            if request_input:
                for feat in plan.get("features") or []:
                    if not isinstance(feat, dict):
                        continue
                    title = str(feat.get("title") or "feature")
                    description = str(feat.get("description") or title)
                    scope = feat.get("scope") or classify_scope(title, description, context.get("notes"))
                    feat["scope"] = scope
                    if scope != "uncertain":
                        continue
                    await request_input(
                        agent_id="enrichment",
                        role="architect",
                        question=(
                            f"The factory wants to add “{title}”. This may be out of scope — implement it?"
                        ),
                        context_detail=description,
                        options=["Yes, implement it", "Skip for now — not in v1 scope"],
                        default_decision="Skip for now — not in v1 scope",
                        task_id=task.id,
                    )

            await self._refresh_context(session, project, context)
            units = plan_from_enrichment_features(
                plan.get("features") or [],
                context.get("notes", []),
                context.get("input_responses", []),
            )
            if not units:
                reason = plan.get("stop_reason") or "no in-scope improvements"
                self.workspace.append_log(
                    project.id,
                    "pipeline.log",
                    f"[{log_prefix}] Enrichment complete: {reason}",
                )
                break

            success, output = await self._run_developer_units(
                session, project, context, units, command="enrichment_implement"
            )
            if not success:
                context["last_failure"] = output
                for _ in range(settings.enrichment_fix_attempts_per_pass):
                    fixed = await self._stage_fix_from_failure(session, project, context)
                    if not fixed:
                        return False
                    success, output = await self._run_developer_units(
                        session, project, context, units, command="enrichment_fix"
                    )
                    if success:
                        break
                if not success:
                    context["last_failure"] = output
                    return False

            test_task = await self.create_task(
                session,
                project.id,
                f"Tests after enrichment pass {pass_number}",
                "Run pytest after enrichment",
                AgentRole.TESTER,
            )
            test_ok, test_output = await self.runner._tester(
                project.id, {**context, "test_stage": "unit"}
            )
            await self.complete_task(session, test_task, test_ok, test_output)
            if not test_ok:
                context["last_failure"] = test_output
                return False

            await self._deploy_live_preview(session, project, context, preview_type="dev", notify=False)
            audit = await audit_live_preview(context)
            context["preview_audit"] = audit

            qa_task = await self.create_task(
                session,
                project.id,
                f"Product QA (pass {pass_number})",
                "Evaluate live preview quality",
                AgentRole.TESTER,
            )
            qa_ok, qa_output = await self.runner._tester(
                project.id, {**context, "test_stage": "product_qa"}
            )
            await self.complete_task(session, qa_task, qa_ok, qa_output)
            context["product_qa"] = qa_output

            passes_done += 1
            context["enrichment_passes_completed"] = passes_done
            await self._log_progress(
                session,
                project.id,
                "enrichment",
                f"Enrichment pass {pass_number} complete",
                f"Implemented {len(units)} improvement(s); QA {'passed' if qa_ok else 'noted issues'}",
            )

        context[completion_key] = True
        return True

    async def _stage_autonomous_enrichment(self, session, project, context) -> bool:
        ok = await self._run_enrichment_passes(
            session,
            project,
            context,
            max_passes=settings.max_enrichment_passes,
            completion_key="enrichment_complete",
            log_prefix="enrichment",
        )
        if ok:
            context["enrichment_complete"] = True
            await self.transition(session, project, advance_project(ProjectState.IMPLEMENTING))
        return ok

    async def _stage_post_smoke_enrichment(self, session, project, context) -> bool:
        ok = await self._run_enrichment_passes(
            session,
            project,
            context,
            max_passes=1,
            completion_key="post_smoke_enrichment_complete",
            log_prefix="pre-review",
        )
        if ok:
            context["post_smoke_enrichment_complete"] = True
        return ok

    async def _stage_implementing(self, session, project, context) -> bool:
        await self._refresh_context(session, project, context)
        success, output = await self._run_parallel_developers(session, project, context)
        if not success:
            context["last_failure"] = output
            return False

        stream_count = len(context.get("work_plan", {}).get("units", []))
        max_parallel = (context.get("work_plan", {}).get("concurrency") or {}).get("max_parallel")
        parallel_label = (
            f"Parallel implementation ({stream_count} streams, max {max_parallel} concurrent)"
            if max_parallel
            else f"Parallel implementation ({stream_count} agents)"
        )
        await self._log_progress(
            session,
            project.id,
            "implementation",
            parallel_label,
            output[:300],
        )
        first_preview = self.workspace.load_metadata(project.id).get("preview_status") != "running"
        preview_ok = await self._deploy_live_preview(
            session,
            project,
            context,
            preview_type="dev",
            notify=first_preview,
        )
        return preview_ok or not context.get("last_failure")

    async def _stage_unit_testing(self, session, project, context) -> bool:
        await self._ensure_runnable_app(project)
        task = await self.create_task(
            session, project.id, "Unit tests", "Run pytest unit tests", AgentRole.TESTER
        )
        success, output = await self.runner._tester(project.id, {**context, "test_stage": "unit"})
        await self.complete_task(session, task, success, output)
        await self.emit(
            session, EventType.TEST_COMPLETED, project.id, task.id, payload={"passed": success, "stage": "unit"}
        )
        if success:
            context["unit_testing_complete"] = True
            await self._log_progress(
                session,
                project.id,
                "test",
                "Unit tests passed",
                output[:200] if output else "All unit tests green",
            )
        else:
            context["last_failure"] = output
        return success

    async def _stage_integration_testing(self, session, project, context) -> bool:
        task = await self.create_task(
            session, project.id, "Integration tests", "Run integration tests", AgentRole.TESTER
        )
        success, output = await self.runner._tester(
            project.id, {**context, "test_stage": "integration"}
        )
        await self.complete_task(session, task, success, output)
        await self.emit(
            session,
            EventType.TEST_COMPLETED,
            project.id,
            task.id,
            payload={"passed": success, "stage": "integration"},
        )
        if success:
            context["tests_passed"] = True
            await self._log_progress(
                session,
                project.id,
                "test",
                "Integration tests passed",
                "API workflow validated end-to-end",
            )
            await self.transition(session, project, advance_project(ProjectState.UNIT_TESTING))
        else:
            context["last_failure"] = output
        return success

    async def _stage_docker_build(self, session, project, context) -> bool:
        build_id = f"build-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        tag = f"factory/{project.name.lower().replace(' ', '-')}:{build_id}"
        context["image_tag"] = tag
        context["build_id"] = build_id

        if self.runner.docker_available():
            success, output = await self.runner.docker_build(project.id, tag)
        else:
            # Simulate build when Docker unavailable (dev without socket)
            success = True
            output = "Docker not available — simulated build success"
            self.workspace.append_log(project.id, "pipeline.log", f"[build] simulated {tag}")

        await self.emit(
            session,
            EventType.AGENT_COMMAND_FINISHED,
            project.id,
            payload={"command": "docker build", "success": success, "tag": tag},
        )

        if success:
            project.image_tag = tag
            await session.commit()
            await self._log_progress(
                session,
                project.id,
                "deploy",
                "Docker image built",
                f"Tagged as {tag}",
            )
            await self.transition(session, project, advance_project(ProjectState.INTEGRATION_TESTING))
        else:
            context["last_failure"] = output
        return success

    async def _stage_staging_deploy(self, session, project, context) -> bool:
        tag = context.get("image_tag", project.image_tag or "none")

        await self.emit(
            session,
            EventType.DEPLOYMENT_STARTED,
            project.id,
            payload={"environment": "staging", "image_tag": tag},
        )

        success = await self._deploy_live_preview(
            session,
            project,
            context,
            preview_type="docker",
            image_tag=tag,
        )

        if success:
            await self.transition(session, project, advance_project(ProjectState.DOCKER_BUILD))
        else:
            if not context.get("last_failure"):
                context["last_failure"] = "Staging deploy failed"
        return success

    async def _stage_smoke_testing(self, session, project, context) -> bool:
        task = await self.create_task(
            session, project.id, "Smoke tests", "Health check on staging", AgentRole.TESTER
        )

        if self.runner.docker_available() and context.get("preview_upstream"):
            success, output = await self.runner._tester(
                project.id, {**context, "test_stage": "smoke"}
            )
        elif self.runner.docker_available():
            success = False
            output = "Smoke test skipped — live preview is not running"
        else:
            success = True
            output = "Simulated smoke test pass"

        await self.complete_task(session, task, success, output)
        await self.emit(
            session,
            EventType.TEST_COMPLETED,
            project.id,
            task.id,
            payload={"passed": success, "stage": "smoke"},
        )
        if success:
            context["smoke_testing_complete"] = True
            await self._log_progress(
                session,
                project.id,
                "test",
                "Smoke tests passed",
                output[:200] if output else "Health check OK on staging",
            )
        else:
            context["last_failure"] = output
        return success

    async def _stage_review(self, session, project, context) -> bool:
        await self._refresh_context(session, project, context)
        context["tests_passed"] = True
        review_path = self.workspace.artifacts_dir(project.id) / "review.json"
        if review_path.exists():
            review_path.unlink()
        task = await self.create_task(
            session, project.id, "Code review", "Reviewer agent checklist", AgentRole.REVIEWER
        )
        run = await self.runner.run(
            AgentRole.REVIEWER, project.id, task.id, str(self.workspace.repo_dir(project.id)), context
        )
        await self.complete_task(
            session, task, run.success, run.output, agent_id=run.agent_id or None, cursor_url=run.cursor_url
        )
        if run.success:
            await self._log_progress(
                session,
                project.id,
                "review",
                "Review approved",
                "All acceptance criteria met — ready for production promotion",
            )
            await self.transition(session, project, advance_project(ProjectState.SMOKE_TESTING))
            await create_notification(
                session,
                project.id,
                NotificationType.REVIEW_READY,
                "Ready for production",
                f"{project.name} passed review. Promote to production when ready.",
                action="overview",
            )
            plan = resolve_branch_plan(project)
            if plan.isolated and plan.work_branch:
                await create_notification(
                    session,
                    project.id,
                    NotificationType.MERGE_READY,
                    "Merge to main?",
                    (
                        f"Factory work is on `{plan.work_branch}`. Your production branch "
                        f"(`{plan.base_branch}`) is unchanged. Merge when you're ready, "
                        f"or keep iterating on the factory branch."
                    ),
                    action="merge",
                )
                await create_input_request(
                    session,
                    project.id,
                    agent_id="pipeline",
                    role="reviewer",
                    question=(
                        f"Merge factory branch `{plan.work_branch}` into `{plan.base_branch}` now?"
                    ),
                    default_decision="Keep on factory branch for now",
                    context_detail=(
                        "Use the dashboard Merge to main button when you want production updated. "
                        "The factory never merges without your approval."
                    ),
                    options=["Merge to main now", "Keep on factory branch"],
                )
        return run.success

    async def _stage_production(self, session, project, context) -> bool:
        meta = self.workspace.load_metadata(project.id)
        origin = context.get("preview_origin") or await get_preview_origin(session)
        preview = preview_from_metadata(meta, origin=origin, project_id=project.id)
        prod_url = preview["preview_url"] or ""
        port = preview.get("preview_port") or context.get("staging_port")

        dep = DeploymentRow(
            project_id=project.id,
            environment="production",
            image_tag=project.image_tag or context.get("image_tag", ""),
            url=prod_url,
            port=port,
            status="running",
        )
        session.add(dep)
        await session.commit()

        meta["production_url"] = prod_url
        meta["preview_type"] = "production"
        self.workspace.save_metadata(project.id, meta)

        await self.emit(
            session,
            EventType.DEPLOYMENT_FINISHED,
            project.id,
            payload={"environment": "production", "url": prod_url},
        )
        await self.transition(session, project, advance_project(ProjectState.REVIEW))
        await create_notification(
            session,
            project.id,
            NotificationType.PROJECT_FINISHED,
            "Project deployed to production",
            f"{project.name} is live at {prod_url or 'production'}",
            action="overview",
        )
        return True

    async def promote_to_production(self, project_id: UUID) -> bool:
        async with SessionLocal() as session:
            project = await session.get(ProjectRow, project_id)
            if not project or ProjectState(project.state) != ProjectState.REVIEW:
                return False
            context = {"tests_passed": True, "image_tag": project.image_tag}
            return await self._stage_production(session, project, context)


pipeline_executor = PipelineExecutor()
