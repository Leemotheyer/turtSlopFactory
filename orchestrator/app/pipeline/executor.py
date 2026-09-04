"""Pipeline executor: orchestration loop, failure control, and stage delegates.

Stage bodies live in :mod:`app.pipeline.stages`; the executor owns the control
loop (closed feedback: execute → observe → evaluate → diagnose → re-plan),
persistent run metrics, and the escalation ladder (infra retry → developer fix
→ human block).
"""

import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.factory import create_agent_runner
from app.agents.prompt_builder import prompt_version_for_role
from app.config import settings
from app.database import SessionLocal
from app.db_models import PipelineRunRow, ProjectRow, TaskRow
from app.events import event_bus
from app.models import AgentRole, EventType, FactoryEvent, NotificationType, ProjectState, TaskStatus
from app.pipeline.stages import (
    BUILD_STAGES,
    POST_PRODUCTION_STAGES,
    SUBSTAGE_IMPLEMENTING,
    SUBSTAGE_UNIT_TESTING,
    StageSpec,
)
from app.pipeline.stages import (
    acceptance as acceptance_stage,
)
from app.pipeline.stages import (
    adversary as adversary_stage,
)
from app.pipeline.stages import (
    build_deploy as build_deploy_stage,
)
from app.pipeline.stages import (
    enrichment as enrichment_stage,
)
from app.pipeline.stages import (
    implementing as implementing_stage,
)
from app.pipeline.stages import (
    planning as planning_stage,
)
from app.pipeline.stages import (
    post_production as post_production_stage,
)
from app.pipeline.stages import (
    preview_deploy as preview_deploy_stage,
)
from app.pipeline.stages import (
    review as review_stage,
)
from app.pipeline.stages import (
    testing as testing_stage,
)
from app.services.agent_rules import load_rules_context
from app.services.diagnosis import diagnose_failure
from app.services.discovery import get_discovery
from app.services.factory_settings import get_agent_backend, get_preview_origin
from app.services.git_branching import resolve_branch_plan, setup_project_branches
from app.services.input_requests import create_input_request, get_input_responses_for_agents
from app.services.notes import get_notes_for_agents
from app.services.notifications import create_notification
from app.services.pipeline_control import (
    archive_project_cloud_agents,
    clear_live_agents,
    set_pipeline_paused,
)
from app.services.preview import (
    build_preview_url,
    preview_path,
    preview_upstream,
)
from app.services.preview_manager import dev_preview_image_tag, stop_preview
from app.services.preview_spec import load_preview_spec
from app.services.progress import record_progress
from app.services.repo_analysis import analyze_repo
from app.services.secrets import (
    ensure_env_placeholder,
    get_env_status_for_agents,
    get_github_token,
    maybe_request_github_token,
    scan_and_ensure_env_placeholders,
)
from app.services.self_propelling import mark_cycle_started
from app.state_machine import (
    block_autonomous,
    fail_project,
    normalize_pipeline_gate,
    parse_project_state,
    pipeline_gate_index,
)
from app.testing.runner import TestRunner
from app.workspace.manager import WorkspaceManager
from app.workspace.scaffolder import ensure_dockerfile, scaffold_base

logger = logging.getLogger(__name__)

# Back-compat aliases (used by tests and older callers).
_STAGE_IMPLEMENTING = SUBSTAGE_IMPLEMENTING
_STAGE_UNIT_TESTING = SUBSTAGE_UNIT_TESTING

_MAX_INFRA_RETRIES = 2


class PipelineStopped(Exception):
    """Raised when the user requests a hard stop of the pipeline."""


class PipelineExecutor:
    def __init__(self) -> None:
        self.workspace = WorkspaceManager()
        self.runner = create_agent_runner(self.workspace)
        self.test_runner = TestRunner()
        self._running: set[UUID] = set()
        self._stop_requested: set[UUID] = set()
        self._pipeline_tasks: dict[UUID, asyncio.Task] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Run/stop bookkeeping
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Failed-gate persistence
    # ------------------------------------------------------------------

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
            return parse_project_state(raw)
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

    # ------------------------------------------------------------------
    # Stage scheduling
    # ------------------------------------------------------------------

    def _stage_is_due(
        self,
        *,
        current_gate: ProjectState,
        spec: StageSpec,
        context: dict,
    ) -> bool:
        if spec.completes and context.get(spec.completes):
            return False

        if context.get("post_production") and spec.gate == ProjectState.PRODUCTION:
            if current_gate != ProjectState.PRODUCTION:
                return False
            if spec.requires and not context.get(spec.requires):
                return False
            return True

        current_idx = pipeline_gate_index(current_gate)
        expected_idx = pipeline_gate_index(spec.gate)
        if current_idx is None or expected_idx is None:
            return False
        if current_idx > expected_idx:
            return False
        if spec.requires and not context.get(spec.requires):
            return False
        return True

    async def _run_stage_sequence(
        self,
        session: AsyncSession,
        project: ProjectRow,
        context: dict,
        specs: tuple[StageSpec, ...],
    ) -> None:
        for spec in specs:
            self._check_stop(project.id)
            await session.refresh(project)
            current = parse_project_state(project.state)

            if current == ProjectState.AUTONOMOUSLY_BLOCKED:
                break
            if current == ProjectState.PRODUCTION and not context.get("post_production"):
                break

            failed = self._load_failed_gate(project.id, context)
            if context.get("post_production") and current == ProjectState.PRODUCTION:
                current_gate = ProjectState.PRODUCTION
            else:
                current_gate = normalize_pipeline_gate(current, failed)
                if current_gate is None:
                    logger.warning(
                        "Pipeline stopped for %s: state %s is not runnable",
                        project.id,
                        current.value,
                    )
                    break

            if not self._stage_is_due(current_gate=current_gate, spec=spec, context=context):
                continue

            if current != spec.gate:
                await self.transition(session, project, spec.gate)

            stage_fn = getattr(self, spec.method)
            success = await stage_fn(session, project, context)
            await self._refresh_context(session, project, context)
            if not success:
                await self._handle_failure(
                    session,
                    project,
                    context,
                    failed_at=spec.gate,
                    failed_substage=spec.substage,
                )
                break

            if spec.completes:
                context[spec.completes] = True
            if context.get("fix_attempt") or context.get("infra_retries"):
                from app.services.memory import resolve_failures_for_gate

                await resolve_failures_for_gate(
                    session, project.id, spec.gate.value, resolution="stage passed after fix"
                )
            self._save_failed_gate(project.id, None)
            context.pop("failed_gate", None)
            context.pop("failed_substage", None)

    # ------------------------------------------------------------------
    # Scaffolding / context helpers
    # ------------------------------------------------------------------

    async def _ensure_repo_scaffold(self, project: ProjectRow, context: dict) -> None:
        repo = self.workspace.repo_dir(project.id)
        analysis = context.get("repo_analysis") or {}
        if context.get("incremental") or analysis.get("has_existing_app") or (repo / "requirements.txt").exists():
            return
        lock = context.setdefault("_scaffold_lock", asyncio.Lock())
        async with lock:
            if not (repo / "requirements.txt").exists():
                scaffold_base(repo, project.name, project.description)

    async def _ensure_runnable_app(self, project: ProjectRow, context: dict | None = None) -> None:
        """Guarantee app/main.py and tests exist with valid syntax before preview or pytest."""
        repo = self.workspace.repo_dir(project.id)
        analysis = (context or {}).get("repo_analysis")
        if not analysis and project.repo_url and (repo / ".git").exists():
            analysis = analyze_repo(repo)
        if analysis and analysis.get("has_existing_app"):
            if ensure_dockerfile(repo):
                self.workspace.append_log(
                    project.id,
                    "pipeline.log",
                    "[scaffold] Added missing Dockerfile for existing repo (layout preserved)",
                )
            return

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

    # ------------------------------------------------------------------
    # Events / tasks
    # ------------------------------------------------------------------

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
        prompt_version = prompt_version_for_role(role)
        row = TaskRow(
            project_id=project_id,
            title=title,
            description=description,
            role=role.value,
            status=TaskStatus.RUNNING.value,
            prompt_version=prompt_version,
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
                "prompt_version": prompt_version,
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

    # ------------------------------------------------------------------
    # Stop handling
    # ------------------------------------------------------------------

    async def _handle_stop(
        self,
        session: AsyncSession,
        project_id: UUID,
        project: ProjectRow,
    ) -> None:
        await self._finalize_stop(session, project_id, project)

    async def _finalize_stop(
        self,
        session: AsyncSession,
        project_id: UUID,
        project: ProjectRow | None,
    ) -> None:
        meta = self.workspace.load_metadata(project_id)
        if meta.get("stop_cleanup_done"):
            return
        set_pipeline_paused(project_id, True)
        await archive_project_cloud_agents(session, project_id)
        await self._cancel_running_tasks(session, project_id)
        clear_live_agents(project_id)
        try:
            await stop_preview(
                project_id,
                ephemeral_image=dev_preview_image_tag(project_id),
            )
        except Exception:
            logger.exception("Failed to stop preview while stopping pipeline for %s", project_id)
        self.workspace.append_log(project_id, "pipeline.log", "[stop] Pipeline stopped by user")
        meta = self.workspace.load_metadata(project_id)
        meta["stop_cleanup_done"] = True
        self.workspace.save_metadata(project_id, meta)
        if project:
            await self.emit(
                session,
                EventType.PIPELINE_STOPPED,
                project_id,
                payload={"state": project.state, "reason": "user_requested"},
            )

    async def force_stop(self, project_id: UUID) -> None:
        """Pause the project and tear down in-flight work."""
        set_pipeline_paused(project_id, True)
        if project_id in self._running:
            self.request_stop(project_id)
        async with SessionLocal() as session:
            project = await session.get(ProjectRow, project_id)
            await self._finalize_stop(session, project_id, project)

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

    # ------------------------------------------------------------------
    # Context refresh
    # ------------------------------------------------------------------

    async def _refresh_context(self, session: AsyncSession, project: ProjectRow, context: dict) -> None:
        context["notes"] = await get_notes_for_agents(session, project.id)
        context.update(await load_rules_context(session, project))
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
        context["incremental"] = (
            context.get("fix_attempt", 0) > 0
            or (repo / "app" / "main.py").exists()
            or bool(project.repo_url)
        )
        if project.repo_url and (repo / ".git").exists():
            analysis = analyze_repo(repo)
            context["repo_analysis"] = analysis
        meta = self.workspace.load_metadata(project.id)
        context["original_description"] = meta.get("original_description") or project.description
        preview_url = build_preview_url(project.id, origin=origin)
        context["preview_url"] = meta.get("preview_url") or preview_url
        context["preview_path"] = preview_path(project.id)
        context["preview_status"] = meta.get("preview_status")
        context["preview_upstream"] = preview_upstream(project.id, meta)
        spec = load_preview_spec(repo)
        context["preview_health_path"] = meta.get("preview_health_path") or spec.path
        context["preview_app_port"] = meta.get("preview_app_port") or spec.port
        context["should_stop"] = lambda: self.is_stop_requested(project.id)
        context["max_enrichment_passes"] = self._resolve_max_enrichment_passes(project)

        from app.services.contracts import get_latest_contract
        from app.services.memory import load_project_memory
        from app.services.project_settings import apply_project_settings_to_context
        from app.services.system_map import load_git_history

        if context.get("contract") is None:
            context["contract"] = await get_latest_contract(session, project.id)
        context["project_memory"] = await load_project_memory(
            session, project.id, gate=project.state
        )
        context["review_ever_approved"] = bool(meta.get("review_ever_approved"))
        apply_project_settings_to_context(project, context)
        if project.repo_url and (repo / ".git").exists():
            context["git_history"] = load_git_history(repo)

        await self._scan_env_placeholders(session, project, context)

    def _resolve_max_enrichment_passes(self, project: ProjectRow) -> int:
        if project.max_enrichment_passes is not None:
            return max(0, project.max_enrichment_passes)
        return settings.max_enrichment_passes

    def _resolve_max_fix_attempts(self, project: ProjectRow) -> int:
        from app.services.project_settings import resolve_max_fix_attempts

        return resolve_max_fix_attempts(project)

    async def _scan_env_placeholders(
        self, session: AsyncSession, project: ProjectRow, context: dict
    ) -> None:
        texts = [project.description or ""]
        texts.append(context.get("global_agent_rules") or "")
        texts.append(context.get("project_agent_rules") or "")
        for note in context.get("notes") or []:
            texts.append(str(note.get("content") or ""))
        for artifact in ("requirements.md", "architecture.md"):
            if artifact in self.workspace.list_artifacts(project.id):
                texts.append(self.workspace.read_artifact(project.id, artifact) or "")
        audit = context.get("preview_audit") or {}
        for issue in audit.get("issues") or []:
            texts.append(str(issue))
        configured = set(context.get("env_status", {}).get("configured_keys") or [])
        created = await scan_and_ensure_env_placeholders(
            session, project.id, texts, configured_keys=configured
        )
        if created:
            context["env_status"] = await get_env_status_for_agents(session, project.id)
            self.workspace.append_log(
                project.id,
                "pipeline.log",
                f"[secrets] Created placeholder env slot(s): {', '.join(created)}",
            )

    def _save_pipeline_substage(self, project_id: UUID, payload: dict | None) -> None:
        meta = self.workspace.load_metadata(project_id)
        if payload is None:
            meta.pop("pipeline_substage", None)
        else:
            meta["pipeline_substage"] = payload
        self.workspace.save_metadata(project_id, meta)

    def _save_enrichment_progress(self, project_id: UUID, payload: dict | None) -> None:
        meta = self.workspace.load_metadata(project_id)
        if payload is None:
            meta.pop("enrichment", None)
        else:
            meta["enrichment"] = payload
        self.workspace.save_metadata(project_id, meta)

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

    # ------------------------------------------------------------------
    # Stage delegates (kept as methods so tests can monkeypatch them)
    # ------------------------------------------------------------------

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
        return await preview_deploy_stage.deploy_live_preview(
            self,
            session,
            project,
            context,
            preview_type=preview_type,
            image_tag=image_tag,
            notify=notify,
        )

    async def _stage_fix_from_failure(self, session, project, context) -> bool:
        return await implementing_stage.stage_fix_from_failure(self, session, project, context)

    async def _stage_planning(self, session, project, context) -> bool:
        return await planning_stage.stage_planning(self, session, project, context)

    async def _stage_implementing(self, session, project, context) -> bool:
        return await implementing_stage.stage_implementing(self, session, project, context)

    async def _stage_unit_testing(self, session, project, context) -> bool:
        return await testing_stage.stage_unit_testing(self, session, project, context)

    async def _stage_autonomous_enrichment(self, session, project, context) -> bool:
        return await enrichment_stage.stage_autonomous_enrichment(self, session, project, context)

    async def _stage_integration_testing(self, session, project, context) -> bool:
        return await testing_stage.stage_integration_testing(self, session, project, context)

    async def _stage_docker_build(self, session, project, context) -> bool:
        return await build_deploy_stage.stage_docker_build(self, session, project, context)

    async def _stage_staging_deploy(self, session, project, context) -> bool:
        return await build_deploy_stage.stage_staging_deploy(self, session, project, context)

    async def _stage_smoke_testing(self, session, project, context) -> bool:
        return await testing_stage.stage_smoke_testing(self, session, project, context)

    async def _stage_post_smoke_enrichment(self, session, project, context) -> bool:
        return await enrichment_stage.stage_post_smoke_enrichment(self, session, project, context)

    async def _stage_adversary(self, session, project, context) -> bool:
        return await adversary_stage.stage_adversary(self, session, project, context)

    async def _stage_acceptance(self, session, project, context) -> bool:
        return await acceptance_stage.stage_acceptance(self, session, project, context)

    async def _stage_review(self, session, project, context) -> bool:
        return await review_stage.stage_review(self, session, project, context)

    async def _stage_production(self, session, project, context) -> bool:
        return await review_stage.stage_production(self, session, project, context)

    async def _stage_post_production_enrichment(self, session, project, context) -> bool:
        return await post_production_stage.stage_post_production_enrichment(
            self, session, project, context
        )

    async def _stage_post_production_testing(self, session, project, context) -> bool:
        return await post_production_stage.stage_post_production_testing(
            self, session, project, context
        )

    async def _stage_post_production_redeploy(self, session, project, context) -> bool:
        return await post_production_stage.stage_post_production_redeploy(
            self, session, project, context
        )

    async def _maybe_run_acceptance_tester(self, session, project, context) -> None:
        """Agent-backed acceptance tester: generate tests/acceptance/ from the contract."""
        if not settings.agent_tester_enabled:
            return
        try:
            backend = await get_agent_backend(session)
        except Exception:
            backend = "local"

        repo = self.workspace.repo_dir(project.id)
        acceptance_dir = repo / "tests" / "acceptance"

        if backend != "local" and context.get("repo_url") and context.get("contract"):
            task = await self.create_task(
                session,
                project.id,
                "Write acceptance tests",
                "Generate tests/acceptance/ from the project contract",
                AgentRole.TESTER,
            )
            run = await self.runner.run(
                AgentRole.TESTER,
                project.id,
                task.id,
                str(repo),
                {**context, "test_stage": "write_acceptance"},
            )
            await self.complete_task(
                session, task, run.success, run.output,
                agent_id=run.agent_id or None, cursor_url=run.cursor_url,
            )

        if acceptance_dir.is_dir() and any(acceptance_dir.glob("test_*.py")):
            task = await self.create_task(
                session,
                project.id,
                "Acceptance tests",
                "Run tests/acceptance/ against the contract",
                AgentRole.TESTER,
            )
            success, output = await self.runner._tester(
                project.id, {**context, "test_stage": "acceptance"}
            )
            await self.complete_task(session, task, success, output)
            from app.services.evidence import record_test_results_evidence

            await record_test_results_evidence(
                session, self.workspace, project.id, stage="acceptance"
            )

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def run_pipeline(self, project_id: UUID) -> None:
        async with self._lock_for(project_id):
            if project_id in self._running:
                return
            self._running.add(project_id)
            self._stop_requested.discard(project_id)

        stopped = False
        run_row_id: UUID | None = None
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

                if parse_project_state(project.state) == ProjectState.AUTONOMOUSLY_BLOCKED:
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
                    if failed_substage == SUBSTAGE_UNIT_TESTING:
                        await self._ensure_runnable_app(project, context)
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

                if parse_project_state(project.state) == ProjectState.REVIEW:
                    context["feedback_iteration"] = True
                    context.pop("implementation_complete", None)
                    context.pop("unit_testing_complete", None)
                    context.pop("enrichment_complete", None)
                    context.pop("post_smoke_enrichment_complete", None)
                    context.pop("adversary_complete", None)
                    context.pop("acceptance_complete", None)
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

                meta = self.workspace.load_metadata(project_id)
                if parse_project_state(project.state) == ProjectState.PRODUCTION and meta.get(
                    "post_production_pending"
                ):
                    context["post_production"] = True
                    context.pop("post_production_enrichment_complete", None)
                    context.pop("post_production_tests_complete", None)
                    context.pop("post_production_redeploy_complete", None)
                    context.pop("post_production_passes_completed", None)
                    cycle_tokens = None
                    try:
                        from app.services.cursor_connection import fetch_usage

                        usage = await fetch_usage(session)
                        if usage.get("connected"):
                            cycle_tokens = (usage.get("tokens") or {}).get("total_tokens")
                    except Exception:
                        pass
                    mark_cycle_started(project_id, self.workspace, cycle_start_tokens=cycle_tokens)
                    self.workspace.append_log(
                        project_id,
                        "pipeline.log",
                        "[post-production] Starting self-propelling improvement cycle",
                    )
                    await self._log_progress(
                        session,
                        project_id,
                        "post_production",
                        "Self-propelling cycle started",
                        "Auditing production preview and planning improvements",
                    )

                async def request_input(**kwargs):
                    return await create_input_request(session, project_id, **kwargs)

                async def request_env(key_name: str, description: str = "", requested_by: str = "agent"):
                    await ensure_env_placeholder(
                        session, project_id, key_name, description, requested_by=requested_by
                    )

                context["request_input"] = request_input
                context["request_env_var"] = request_env
                meta["pipeline_started_at"] = datetime.utcnow().isoformat()
                meta.pop("stop_cleanup_done", None)
                self.workspace.save_metadata(project_id, meta)

                run_row = PipelineRunRow(
                    project_id=project_id,
                    started_at=datetime.utcnow(),
                    mode="post_production" if context.get("post_production") else (
                        "feedback" if context.get("feedback_iteration") else "build"
                    ),
                    outcome="running",
                )
                session.add(run_row)
                await session.commit()
                await session.refresh(run_row)
                run_row_id = run_row.id
                context["pipeline_run_id"] = str(run_row_id)

                specs = POST_PRODUCTION_STAGES if context.get("post_production") else BUILD_STAGES
                await self._run_stage_sequence(session, project, context, specs)

                await self._finalize_run_metrics(session, project, context, run_row_id)

        except PipelineStopped:
            stopped = True
            async with SessionLocal() as session:
                project = await session.get(ProjectRow, project_id)
                if project:
                    await self._handle_stop(session, project_id, project)
                await self._finalize_run_metrics(session, project, None, run_row_id, outcome="stopped")
        except asyncio.CancelledError:
            if project_id in self._stop_requested:
                stopped = True
                async with SessionLocal() as session:
                    project = await session.get(ProjectRow, project_id)
                    if project:
                        await self._handle_stop(session, project_id, project)
                    await self._finalize_run_metrics(
                        session, project, None, run_row_id, outcome="stopped"
                    )
        except Exception:
            if project_id in self._stop_requested:
                stopped = True
                async with SessionLocal() as session:
                    project = await session.get(ProjectRow, project_id)
                    if project:
                        await self._handle_stop(session, project_id, project)
                    await self._finalize_run_metrics(
                        session, project, None, run_row_id, outcome="stopped"
                    )
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
                    await self._finalize_run_metrics(
                        session, project, None, run_row_id, outcome="error"
                    )
        finally:
            async with self._lock_for(project_id):
                self._running.discard(project_id)
                self._stop_requested.discard(project_id)
                meta = self.workspace.load_metadata(project_id)
                if not stopped:
                    meta.pop("live_agents", None)
                    self.workspace.save_metadata(project_id, meta)

    async def _finalize_run_metrics(
        self,
        session: AsyncSession,
        project: ProjectRow | None,
        context: dict | None,
        run_row_id: UUID | None,
        outcome: str | None = None,
    ) -> None:
        if run_row_id is None:
            return
        try:
            run_row = await session.get(PipelineRunRow, run_row_id)
            if run_row is None:
                return
            run_row.finished_at = datetime.utcnow()
            if outcome is None and project is not None:
                state = parse_project_state(project.state)
                if state == ProjectState.AUTONOMOUSLY_BLOCKED:
                    outcome = "blocked"
                elif state in (ProjectState.REVIEW, ProjectState.PRODUCTION):
                    outcome = "completed"
                else:
                    outcome = "incomplete"
            run_row.outcome = outcome or "unknown"
            if context:
                run_row.fix_attempts = int(context.get("fix_attempt") or 0)
                run_row.infra_retries = int(context.get("infra_retries") or 0)
                gates = context.get("gates_failed") or []
                run_row.gates_failed = gates
                run_row.prompt_versions = {
                    role.value: prompt_version_for_role(role) for role in AgentRole
                }

            # Human interventions during this run window.
            from app.db_models import InputRequestRow

            started = run_row.started_at
            result = await session.execute(
                select(InputRequestRow.status).where(
                    InputRequestRow.project_id == run_row.project_id,
                    InputRequestRow.created_at >= started,
                )
            )
            statuses = [row[0] for row in result]
            run_row.human_interventions = sum(1 for s in statuses if s == "answered")
            run_row.auto_resolved_inputs = sum(1 for s in statuses if s == "auto_resolved")
            await session.commit()
        except Exception:
            logger.exception("Could not finalize pipeline run metrics")

    # ------------------------------------------------------------------
    # Failure control (diagnose → infra retry → fix → escalate)
    # ------------------------------------------------------------------

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

        if failed_substage == SUBSTAGE_UNIT_TESTING:
            context.pop("implementation_complete", None)
        elif failed_at == ProjectState.PLANNING:
            context.pop("implementation_complete", None)

        if context.get("last_failure"):
            self._persist_last_failure(project.id, context)

        gates_failed = context.setdefault("gates_failed", [])
        gates_failed.append(
            {"gate": failed_at.value, "substage": failed_substage, "at": datetime.utcnow().isoformat()}
        )

        try:
            await self.transition(session, project, fail_project(failed_at))
        except Exception:
            await self.transition(session, project, ProjectState.DIAGNOSING)

        # DIAGNOSING is a real step: classify the failure before spending a
        # developer fix attempt on it.
        diagnosis = diagnose_failure(
            str(context.get("last_failure") or ""),
            logs_tail=self._pipeline_log_tail(project.id),
            gate=failed_at.value,
            substage=failed_substage,
        )
        context["failure_diagnosis"] = diagnosis
        self.workspace.append_log(
            project.id,
            "pipeline.log",
            f"[diagnosis] {failed_at.value}"
            + (f"/{failed_substage}" if failed_substage else "")
            + f" classified as {diagnosis['error_class']}: {diagnosis['hint'][:200]}",
        )

        from app.services.memory import record_failure

        failure_record_id = await record_failure(
            session,
            project.id,
            gate=failed_at.value,
            substage=failed_substage,
            error_class=diagnosis["error_class"],
            summary=str(context.get("last_failure") or "")[:2000],
            attempt=int(context.get("fix_attempt") or 0) + 1,
        )
        context["last_failure_record_id"] = str(failure_record_id) if failure_record_id else None
        if failure_record_id and diagnosis["error_class"] == "app":
            # Regression-test policy: the fix must pin this failure with a test.
            context["regression_test_hint"] = f"test_fix_{str(failure_record_id)[:8]}.py"

        # Infra failures retry without consuming a fix attempt (cheap rung of
        # the failure ladder) — the code is not the problem.
        if diagnosis["error_class"] == "infra":
            infra_retries = int(context.get("infra_retries") or 0)
            if infra_retries < _MAX_INFRA_RETRIES:
                context["infra_retries"] = infra_retries + 1
                self.workspace.append_log(
                    project.id,
                    "pipeline.log",
                    f"[diagnosis] Infra failure — retry {infra_retries + 1}/{_MAX_INFRA_RETRIES} "
                    "without consuming a fix attempt",
                )
                await self.transition(session, project, ProjectState.FIXING)
                await self.transition(session, project, failed_at)
                specs = (
                    POST_PRODUCTION_STAGES if context.get("post_production") else BUILD_STAGES
                )
                await self._run_stage_sequence(session, project, context, specs)
                return

        attempt = context.get("fix_attempt", 0) + 1
        context["fix_attempt"] = attempt

        if attempt >= self._resolve_max_fix_attempts(project):
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

        if failed_substage == SUBSTAGE_UNIT_TESTING:
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

        specs = POST_PRODUCTION_STAGES if context.get("post_production") else BUILD_STAGES
        await self._run_stage_sequence(session, project, context, specs)

    def _pipeline_log_tail(self, project_id: UUID, lines: int = 40) -> str:
        try:
            log_path = self.workspace.logs_dir(project_id) / "pipeline.log"
            if not log_path.is_file():
                return ""
            content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    async def promote_to_production(self, project_id: UUID) -> bool:
        async with SessionLocal() as session:
            project = await session.get(ProjectRow, project_id)
            if not project or parse_project_state(project.state) != ProjectState.REVIEW:
                return False
            context = {"tests_passed": True, "image_tag": project.image_tag}
            return await self._stage_production(session, project, context)


pipeline_executor = PipelineExecutor()
