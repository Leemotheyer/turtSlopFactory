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
from app.services.factory_settings import get_agent_backend, get_preview_host
from app.services.work_planner import optimize_work_units, plan_parallel_work, work_plan_to_dict
from app.state_machine import (
    advance_project,
    block_autonomous,
    fail_project,
    normalize_pipeline_gate,
    pipeline_gate_index,
)
from app.services.preview import (
    allocate_preview_port,
    build_preview_url,
    get_preview_port,
    preview_from_metadata,
    preview_upstream,
    update_preview_metadata,
)
from app.services.preview_manager import (
    preview_container_name,
    start_dev_preview,
    start_docker_preview,
    stop_preview,
)
from app.workspace.manager import WorkspaceManager
from app.workspace.scaffolder import scaffold_base

logger = logging.getLogger(__name__)

# Two substages run while the project state remains IMPLEMENTING.
_STAGE_IMPLEMENTING = "implementing"
_STAGE_UNIT_TESTING = "unit_testing"


class PipelineExecutor:
    def __init__(self) -> None:
        self.workspace = WorkspaceManager()
        self.runner = create_agent_runner(self.workspace)
        self._running: set[UUID] = set()
        self._locks: dict[UUID, asyncio.Lock] = {}

    def is_running(self, project_id: UUID) -> bool:
        return project_id in self._running

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
        if substage == _STAGE_UNIT_TESTING:
            context["implementation_complete"] = True
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
                return context.get("implementation_complete", False)
            return not context.get("implementation_complete", False)
        return True

    async def _ensure_repo_scaffold(self, project: ProjectRow, context: dict) -> None:
        repo = self.workspace.repo_dir(project.id)
        if context.get("incremental") or (repo / "requirements.txt").exists():
            return
        lock = context.setdefault("_scaffold_lock", asyncio.Lock())
        async with lock:
            if not (repo / "requirements.txt").exists():
                scaffold_base(repo, project.name, project.description)

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
        return row

    async def complete_task(
        self, session: AsyncSession, task: TaskRow, success: bool, output: str
    ) -> None:
        task.status = TaskStatus.COMPLETED.value if success else TaskStatus.FAILED.value
        task.updated_at = datetime.utcnow()
        await session.commit()
        await self.emit(
            session,
            EventType.AGENT_COMMAND_FINISHED,
            task.project_id,
            task.id,
            agent_id=f"{task.role}-{str(task.id)[:8]}",
            payload={"success": success, "output": output[:2000]},
        )

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
        context["preview_host"] = await get_preview_host(session)
        repo = self.workspace.repo_dir(project.id)
        context["incremental"] = context.get("fix_attempt", 0) > 0 or (repo / "app" / "main.py").exists()

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
        """Start or replace a project preview (internal port or isolated Docker network)."""
        meta = self.workspace.load_metadata(project.id)
        host = context.get("preview_host") or await get_preview_host(session)
        preview_url = build_preview_url(project.id, host=host)
        runtime_env = await get_secrets_for_runtime(session, project.id)

        await stop_preview(project.id, container_name=meta.get("preview_container"))

        port: int | None = None
        container_id: str | None = None
        container_name: str | None = None
        process_id: str | None = None
        backend = "simulated"

        if preview_type == "dev":
            port = await allocate_preview_port(meta)
            repo = self.workspace.repo_dir(project.id)
            log_path = self.workspace.logs_dir(project.id) / "preview-dev.log"
            success, output, process_id = await start_dev_preview(
                project.id, repo, port, log_path
            )
            backend = "subprocess"
            context["preview_backend"] = backend
            context["staging_port"] = port
            context["preview_port"] = port
        elif self.runner.docker_available():
            tag = image_tag or project.image_tag or context.get("image_tag", "none")
            if tag == "none":
                success, output, container_id = False, "No image tag", None
            else:
                container_name = preview_container_name(project.id)
                success, output, container_id = await start_docker_preview(
                    project.id, tag, env_vars=runtime_env
                )
                backend = "docker"
                context["preview_backend"] = backend
                context["preview_container"] = container_name
        else:
            success = True
            output = f"No Docker — simulated preview at {preview_url}"
            backend = "simulated"

        status = "running" if success else "failed"
        if not success:
            self.workspace.append_log(project.id, "pipeline.log", f"[preview] failed: {output[:500]}")

        update_preview_metadata(
            meta,
            project_id=project.id,
            port=port,
            preview_type=preview_type,
            status=status,
            backend=backend,
            host=host,
            container_id=container_id,
            container_name=container_name,
            process_id=process_id,
        )
        self.workspace.save_metadata(project.id, meta)
        context["preview_upstream"] = preview_upstream(project.id, meta)

        dep = DeploymentRow(
            project_id=project.id,
            environment="preview" if preview_type == "dev" else "staging",
            image_tag=image_tag or project.image_tag or "dev",
            url=preview_url,
            port=port,
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

                if ProjectState(project.state) == ProjectState.AUTONOMOUSLY_BLOCKED:
                    resume_gate = failed_gate or ProjectState.PLANNING
                    await self.transition(
                        session,
                        project,
                        resume_gate,
                        reason="manual_resume",
                    )
                    context.pop("fix_attempt", None)
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        f"[resume] Unblocked — restarting from {resume_gate.value}",
                    )

                async def request_input(**kwargs):
                    return await create_input_request(session, project_id, **kwargs)

                async def request_env(key_name: str, description: str = "", requested_by: str = "agent"):
                    return await request_env_var(session, project_id, key_name, description, requested_by)

                context["request_input"] = request_input
                context["request_env_var"] = request_env
                meta = self.workspace.load_metadata(project_id)
                meta["pipeline_started_at"] = datetime.utcnow().isoformat()
                self.workspace.save_metadata(project_id, meta)

                stages: list[tuple[ProjectState, str | None, object]] = [
                    (ProjectState.PLANNING, None, self._stage_planning),
                    (ProjectState.IMPLEMENTING, _STAGE_IMPLEMENTING, self._stage_implementing),
                    (ProjectState.IMPLEMENTING, _STAGE_UNIT_TESTING, self._stage_unit_testing),
                    (ProjectState.UNIT_TESTING, None, self._stage_integration_testing),
                    (ProjectState.INTEGRATION_TESTING, None, self._stage_docker_build),
                    (ProjectState.DOCKER_BUILD, None, self._stage_staging_deploy),
                    (ProjectState.STAGING_DEPLOY, None, self._stage_smoke_testing),
                    (ProjectState.SMOKE_TESTING, None, self._stage_review),
                ]

                for expected_gate, substage, stage_fn in stages:
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

        except Exception:
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
            context["implementation_complete"] = True
        elif failed_at == ProjectState.PLANNING:
            context.pop("implementation_complete", None)

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

        retry_stages: list[tuple[ProjectState, str | None, object]] = [
            (ProjectState.PLANNING, None, self._stage_planning),
            (ProjectState.IMPLEMENTING, _STAGE_IMPLEMENTING, self._stage_implementing),
            (ProjectState.IMPLEMENTING, _STAGE_UNIT_TESTING, self._stage_unit_testing),
            (ProjectState.UNIT_TESTING, None, self._stage_integration_testing),
            (ProjectState.INTEGRATION_TESTING, None, self._stage_docker_build),
            (ProjectState.DOCKER_BUILD, None, self._stage_staging_deploy),
            (ProjectState.STAGING_DEPLOY, None, self._stage_smoke_testing),
            (ProjectState.SMOKE_TESTING, None, self._stage_review),
        ]

        failed_idx = pipeline_gate_index(failed_at) or 0
        for expected_gate, substage, stage_fn in retry_stages:
            if (pipeline_gate_index(expected_gate) or 0) < failed_idx:
                continue
            if substage == _STAGE_UNIT_TESTING and not context.get("implementation_complete"):
                continue
            if substage == _STAGE_IMPLEMENTING and context.get("implementation_complete"):
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
        await self.complete_task(session, task, run.success, run.output)
        if run.success:
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
        return run.success

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

        async def run_unit(unit, task_row: TaskRow) -> tuple[TaskRow, bool, str]:
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
                return task_row, run.success, run.output

        results = await asyncio.gather(*[run_unit(u, t) for u, t in task_rows])

        outputs: list[str] = []
        all_ok = True
        for task_row, success, output in results:
            await self.complete_task(session, task_row, success, output)
            outputs.append(output)
            if not success:
                all_ok = False

        combined = "; ".join(outputs)
        return all_ok, combined

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
        first_preview = get_preview_port(self.workspace.load_metadata(project.id)) is None
        await self._deploy_live_preview(
            session,
            project,
            context,
            preview_type="dev",
            notify=first_preview,
        )
        return True

    async def _stage_unit_testing(self, session, project, context) -> bool:
        task = await self.create_task(
            session, project.id, "Unit tests", "Run pytest unit tests", AgentRole.TESTER
        )
        success, output = await self.runner._tester(project.id, {**context, "test_stage": "unit"})
        await self.complete_task(session, task, success, output)
        await self.emit(
            session, EventType.TEST_COMPLETED, project.id, task.id, payload={"passed": success, "stage": "unit"}
        )
        if success:
            await self._log_progress(
                session,
                project.id,
                "test",
                "Unit tests passed",
                output[:200] if output else "All unit tests green",
            )
            await self.transition(session, project, advance_project(ProjectState.IMPLEMENTING))
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
            context["last_failure"] = "Staging deploy failed"
        return success

    async def _stage_smoke_testing(self, session, project, context) -> bool:
        task = await self.create_task(
            session, project.id, "Smoke tests", "Health check on staging", AgentRole.TESTER
        )

        if self.runner.docker_available() and context.get("staging_port"):
            success, output = await self.runner._tester(
                project.id, {**context, "test_stage": "smoke"}
            )
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
            await self._log_progress(
                session,
                project.id,
                "test",
                "Smoke tests passed",
                output[:200] if output else "Health check OK on staging",
            )
            await self.transition(session, project, advance_project(ProjectState.STAGING_DEPLOY))
        else:
            context["last_failure"] = output
        return success

    async def _stage_review(self, session, project, context) -> bool:
        await self._refresh_context(session, project, context)
        task = await self.create_task(
            session, project.id, "Code review", "Reviewer agent checklist", AgentRole.REVIEWER
        )
        run = await self.runner.run(
            AgentRole.REVIEWER, project.id, task.id, str(self.workspace.repo_dir(project.id)), context
        )
        await self.complete_task(session, task, run.success, run.output)
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
        preview = preview_from_metadata(meta, project_id=project.id)
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
