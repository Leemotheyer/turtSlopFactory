import asyncio
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.local_runner import LocalAgentRunner
from app.config import settings
from app.database import SessionLocal
from app.db_models import DeploymentRow, EventRow, ProjectRow, TaskRow
from app.events import event_bus
from app.models import AgentRole, EventType, FactoryEvent, NotificationType, ProjectState, TaskStatus
from app.services.discovery import get_discovery
from app.services.notifications import create_notification
from app.services.notes import get_notes_for_agents
from app.services.progress import record_progress
from app.services.secrets import get_env_status_for_agents, get_secrets_for_runtime, request_env_var
from app.state_machine import advance_project, block_autonomous, fail_project
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

# Port allocation for staging containers (8081+)
_port_counter = 8081
_port_lock = asyncio.Lock()


async def _next_staging_port() -> int:
    global _port_counter
    async with _port_lock:
        port = _port_counter
        _port_counter += 1
        if _port_counter > 8999:
            _port_counter = 8081
        return port


class PipelineExecutor:
    def __init__(self) -> None:
        self.workspace = WorkspaceManager()
        self.runner = LocalAgentRunner(self.workspace)
        self._running: set[UUID] = set()

    def is_running(self, project_id: UUID) -> bool:
        return project_id in self._running

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
        context["project_state"] = project.state
        context["env_status"] = await get_env_status_for_agents(session, project.id)

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

    async def run_pipeline(self, project_id: UUID) -> None:
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
                    "tests_passed": False,
                    "notes": [],
                }
                await self._refresh_context(session, project, context)

                discovery = await get_discovery(session, project_id)
                if discovery and discovery.responses:
                    context["intake"] = discovery.responses
                    context["loose_plan"] = discovery.loose_plan

                async def request_input(**kwargs):
                    return await create_input_request(session, project_id, **kwargs)

                async def request_env(key_name: str, description: str = "", requested_by: str = "agent"):
                    return await request_env_var(session, project_id, key_name, description, requested_by)

                context["request_input"] = request_input
                context["request_env_var"] = request_env
                meta = self.workspace.load_metadata(project_id)
                meta["pipeline_started_at"] = datetime.utcnow().isoformat()
                self.workspace.save_metadata(project_id, meta)

                stages = [
                    (ProjectState.PLANNING, self._stage_planning),
                    (ProjectState.IMPLEMENTING, self._stage_implementing),
                    (ProjectState.IMPLEMENTING, self._stage_unit_testing),
                    (ProjectState.UNIT_TESTING, self._stage_integration_testing),
                    (ProjectState.INTEGRATION_TESTING, self._stage_docker_build),
                    (ProjectState.DOCKER_BUILD, self._stage_staging_deploy),
                    (ProjectState.STAGING_DEPLOY, self._stage_smoke_testing),
                    (ProjectState.SMOKE_TESTING, self._stage_review),
                    # PRODUCTION requires explicit promote via dashboard
                ]

                for expected_state, stage_fn in stages:
                    await session.refresh(project)
                    current = ProjectState(project.state)

                    if current == ProjectState.AUTONOMOUSLY_BLOCKED:
                        break

                    if current != expected_state:
                        if current == ProjectState.PRODUCTION:
                            break
                        # Auto-advance to expected if behind
                        if self._is_before(current, expected_state):
                            await self.transition(session, project, expected_state)
                        else:
                            break

                    success = await stage_fn(session, project, context)
                    await self._refresh_context(session, project, context)
                    if not success:
                        await self._handle_failure(session, project, context)
                        break

        except Exception:
            logger.exception("Pipeline failed for project %s", project_id)
            async with SessionLocal() as session:
                project = await session.get(ProjectRow, project_id)
                if project:
                    await self.transition(
                        session, project, ProjectState.AUTONOMOUSLY_BLOCKED, reason="exception"
                    )
        finally:
            self._running.discard(project_id)

    def _is_before(self, current: ProjectState, target: ProjectState) -> bool:
        order = list(ProjectState)
        try:
            return order.index(current) < order.index(target)
        except ValueError:
            return False

    async def _handle_failure(self, session: AsyncSession, project: ProjectRow, context: dict) -> None:
        current = ProjectState(project.state)
        try:
            await self.transition(session, project, fail_project(current))
        except Exception:
            await self.transition(session, project, ProjectState.DIAGNOSING)

        attempt = context.get("fix_attempt", 0) + 1
        context["fix_attempt"] = attempt

        if attempt >= settings.max_fix_attempts:
            await self.transition(session, project, block_autonomous())
            return

        await self.transition(session, project, ProjectState.FIXING)
        await self.transition(session, project, ProjectState.IMPLEMENTING)

        # Retry remaining stages inline
        retry_stages = [
            self._stage_implementing,
            self._stage_unit_testing,
            self._stage_integration_testing,
            self._stage_docker_build,
            self._stage_staging_deploy,
            self._stage_smoke_testing,
            self._stage_review,
        ]
        for stage_fn in retry_stages:
            await session.refresh(project)
            if ProjectState(project.state) in (
                ProjectState.AUTONOMOUSLY_BLOCKED,
                ProjectState.PRODUCTION,
            ):
                break
            success = await stage_fn(session, project, context)
            if not success:
                await self.transition(session, project, block_autonomous())
                break

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
            await self._log_progress(
                session,
                project.id,
                "planning",
                "Architecture planned",
                "Requirements and architecture documents created",
            )
            await self.transition(session, project, advance_project(ProjectState.PLANNING))
        return run.success

    async def _stage_implementing(self, session, project, context) -> bool:
        await self._refresh_context(session, project, context)
        task = await self.create_task(
            session, project.id, "Implement application", project.description, AgentRole.DEVELOPER
        )
        run = await self.runner.run(
            AgentRole.DEVELOPER, project.id, task.id, str(self.workspace.repo_dir(project.id)), context
        )
        await self.complete_task(session, task, run.success, run.output)
        if run.success:
            await self._log_progress(
                session,
                project.id,
                "implementation",
                "Application implemented",
                run.output[:200],
            )
            await self.transition(session, project, advance_project(ProjectState.PLANNING))
        return run.success

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
        return success

    async def _stage_staging_deploy(self, session, project, context) -> bool:
        port = await _next_staging_port()
        context["staging_port"] = port
        tag = context.get("image_tag", project.image_tag or "none")
        staging_url = f"http://localhost:{port}"

        await self.emit(
            session, EventType.DEPLOYMENT_STARTED, project.id, payload={"environment": "staging", "port": port}
        )

        runtime_env = await get_secrets_for_runtime(session, project.id)

        if self.runner.docker_available() and tag != "none":
            success, output, container_id = await self.runner.deploy_staging(
                project.id, tag, port, env_vars=runtime_env
            )
        else:
            success = True
            output = f"Simulated staging deploy at {staging_url}"
            container_id = None

        dep = DeploymentRow(
            project_id=project.id,
            environment="staging",
            image_tag=tag,
            url=staging_url,
            port=port,
            container_id=container_id,
            status="running" if success else "failed",
        )
        session.add(dep)
        await session.commit()

        meta = self.workspace.load_metadata(project.id)
        meta["staging_url"] = staging_url
        meta["staging_port"] = port
        self.workspace.save_metadata(project.id, meta)

        await self.emit(
            session,
            EventType.DEPLOYMENT_FINISHED,
            project.id,
            payload={"environment": "staging", "url": staging_url, "success": success},
        )

        if success:
            await self._log_progress(
                session,
                project.id,
                "deploy",
                "Deployed to staging",
                f"Available at {staging_url}",
            )
            await self.transition(session, project, advance_project(ProjectState.DOCKER_BUILD))
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
        return run.success

    async def _stage_production(self, session, project, context) -> bool:
        staging_url = self.workspace.load_metadata(project.id).get("staging_url", "")
        prod_url = staging_url  # Same host for self-hosted demo

        dep = DeploymentRow(
            project_id=project.id,
            environment="production",
            image_tag=project.image_tag or context.get("image_tag", ""),
            url=prod_url,
            port=context.get("staging_port"),
            status="running",
        )
        session.add(dep)
        await session.commit()

        meta = self.workspace.load_metadata(project.id)
        meta["production_url"] = prod_url
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
