import json
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.discovery import generate_discovery
from app.config import settings
from app.db_models import DiscoverySessionRow, ProjectRow
from app.events import event_bus
from app.models import (
    DiscoverySession,
    DiscoveryStatus,
    EventType,
    FactoryEvent,
    IntakeField,
    IntakeSubmit,
    NoteType,
    NotificationType,
    ProjectNoteCreate,
    ProjectState,
)
from app.services.agent_rules import combined_rules_text, load_rules_context
from app.services.notifications import create_notification
from app.services.notes import add_note
from app.services.progress import record_progress
from app.services.repo_analysis import (
    analyze_repo,
    fetch_github_readme,
    fetch_github_repo_meta,
    infer_intake_defaults,
)
from app.services.repo_exploration import (
    apply_exploration_to_analysis,
    enrich_intake_from_exploration,
    explore_repo_with_agent,
    needs_agent_repo_exploration,
)
from app.services.secrets import get_github_token
from app.workspace.manager import WorkspaceManager
from app.workspace.provisioner import repo_display_name

logger = logging.getLogger(__name__)
workspace = WorkspaceManager()


def _session_from_row(row: DiscoverySessionRow) -> DiscoverySession:
    return DiscoverySession(
        id=row.id,
        project_id=row.project_id,
        status=DiscoveryStatus(row.status),
        loose_plan=row.loose_plan,
        form_fields=[IntakeField.model_validate(f) for f in (row.form_fields or [])],
        responses=row.responses or {},
        created_at=row.created_at,
        submitted_at=row.submitted_at,
        expires_at=row.expires_at,
    )


async def run_discovery(session: AsyncSession, project_id: UUID, *, force: bool = False) -> DiscoverySession:
    project = await session.get(ProjectRow, project_id)
    if not project:
        raise ValueError("Project not found")

    existing = await get_discovery(session, project_id)
    refreshable_states = (
        ProjectState.REQUESTED.value,
        ProjectState.DISCOVERY.value,
        ProjectState.INTAKE_PENDING.value,
    )

    if existing and not force:
        if existing.status in (
            DiscoveryStatus.AWAITING_USER,
            DiscoveryStatus.SUBMITTED,
            DiscoveryStatus.AUTO_SUBMITTED,
        ):
            return existing
        if (
            existing.status == DiscoveryStatus.GENERATING
            and project.state not in refreshable_states
        ):
            return existing

    if project.state not in refreshable_states and not force:
        if existing:
            return existing
        raise ValueError(f"Discovery not applicable in state {project.state}")

    if existing:
        stale = await session.execute(
            select(DiscoverySessionRow).where(DiscoverySessionRow.project_id == project_id)
        )
        stale_row = stale.scalar_one_or_none()
        if stale_row:
            await session.delete(stale_row)
            await session.commit()

    project.state = ProjectState.DISCOVERY.value
    project.updated_at = datetime.utcnow()

    row = DiscoverySessionRow(
        project_id=project_id,
        status=DiscoveryStatus.GENERATING.value,
    )
    session.add(row)
    await session.commit()

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.DISCOVERY_STARTED,
            project_id=project_id,
            payload={"name": project.name},
        ),
    )

    # Static discovery — analyze linked repo when available for bespoke intake
    rules_ctx = await load_rules_context(session, project)
    repo_context: dict | None = None
    suggested_responses: dict[str, str | list[str]] = {}
    if project.repo_url:
        try:
            repo_path = workspace.repo_dir(project_id)
            token = await get_github_token(session, project_id)
            github_meta = await fetch_github_repo_meta(project.repo_url, github_token=token)
            if not (repo_path / ".git").exists():
                await setup_project_branches(workspace, project, github_token=token)
                await session.commit()
            readme_override = ""
            if not any((repo_path / name).is_file() for name in ("README.md", "readme.md", "Readme.md")):
                readme_override = await fetch_github_readme(project.repo_url, github_token=token)
            analysis = analyze_repo(repo_path, readme_override=readme_override, github_meta=github_meta)
            if not analysis.get("has_existing_app") and github_meta.get("size_kb", 0) >= 50:
                analysis = {
                    **analysis,
                    "has_existing_app": True,
                    "has_substantial_codebase": True,
                    "continuation_mode": "extend",
                }
            if needs_agent_repo_exploration(repo_path, analysis, github_meta):
                exploration = await explore_repo_with_agent(
                    session, project, repo_path, analysis, workspace, rules_context=rules_ctx
                )
                analysis = apply_exploration_to_analysis(analysis, exploration)
                suggested_responses = enrich_intake_from_exploration(
                    infer_intake_defaults(project.description, analysis),
                    exploration,
                    project.description,
                )
            else:
                suggested_responses = infer_intake_defaults(project.description, analysis)
            repo_context = {**analysis, "repo_name": repo_display_name(project.repo_url)}
            workspace.write_artifact(
                project_id, "repo-analysis.json", json.dumps(repo_context, indent=2, default=str)
            )
            mode = repo_context.get("continuation_mode", "greenfield")
            method = repo_context.get("exploration_method", "static")
            workspace.append_log(
                project_id,
                "pipeline.log",
                f"[discovery] Analyzed linked repo ({mode}, via {method}) — "
                f"{analysis.get('source_file_count', 0)} source files, "
                f"pre-filled {len(suggested_responses)} intake hint(s)",
            )
        except Exception as exc:
            logger.warning("Repo analysis during discovery failed for %s: %s", project_id, exc)
            workspace.append_log(project_id, "pipeline.log", f"[discovery] Repo analysis skipped: {exc}")

    loose_plan, form_fields = generate_discovery(
        project.name,
        project.description,
        repo_context=repo_context,
        suggested_responses=suggested_responses,
        global_agent_rules=rules_ctx.get("global_agent_rules", ""),
        project_agent_rules=rules_ctx.get("project_agent_rules", ""),
    )

    row.loose_plan = loose_plan
    row.form_fields = [f.model_dump() for f in form_fields]
    row.status = DiscoveryStatus.AWAITING_USER.value
    row.expires_at = datetime.utcnow() + timedelta(hours=settings.intake_form_timeout_hours)
    if suggested_responses:
        row.responses = {
            k: v for k, v in suggested_responses.items() if v is not None and v != ""
        }

    project.state = ProjectState.INTAKE_PENDING.value
    project.updated_at = datetime.utcnow()

    workspace.write_artifact(project_id, "discovery-plan.md", loose_plan)
    workspace.write_artifact(
        project_id, "intake-form.json", json.dumps([f.model_dump() for f in form_fields], indent=2)
    )

    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.DISCOVERY_COMPLETED,
            project_id=project_id,
            payload={"field_count": len(form_fields)},
        ),
    )

    await record_progress(
        session,
        project_id,
        "discovery",
        "Discovery complete",
        f"Loose plan ready — {len(form_fields)} intake questions for you",
    )

    await create_notification(
        session,
        project_id,
        NotificationType.INTAKE_READY,
        "Intake form ready",
        f"Discovery complete for your project. Fill out the scope form to continue.",
        action="intake",
    )

    return _session_from_row(row)


async def get_discovery(session: AsyncSession, project_id: UUID) -> DiscoverySession | None:
    result = await session.execute(
        select(DiscoverySessionRow).where(DiscoverySessionRow.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    return _session_from_row(row) if row else None


async def submit_intake(
    session: AsyncSession, project_id: UUID, body: IntakeSubmit
) -> DiscoverySession:
    result = await session.execute(
        select(DiscoverySessionRow).where(DiscoverySessionRow.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError("Discovery session not found")
    if row.status not in (DiscoveryStatus.AWAITING_USER.value, DiscoveryStatus.GENERATING.value):
        raise ValueError("Intake already submitted")

    project = await session.get(ProjectRow, project_id)
    if not project:
        raise ValueError("Project not found")

    # Validate required fields
    fields = [IntakeField.model_validate(f) for f in row.form_fields]
    for field in fields:
        if field.required:
            val = body.responses.get(field.id)
            if val is None or (isinstance(val, str) and not val.strip()):
                raise ValueError(f"Required field missing: {field.label}")

    row.responses = body.responses
    row.status = DiscoveryStatus.SUBMITTED.value
    row.submitted_at = datetime.utcnow()

    project.state = ProjectState.PLANNING.value
    project.updated_at = datetime.utcnow()

    # Enrich project description and create structured notes from answers
    await _apply_intake_to_project(session, project_id, project, fields, body.responses)

    workspace.write_artifact(
        project_id, "intake-responses.json", json.dumps(body.responses, indent=2)
    )

    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.INTAKE_SUBMITTED,
            project_id=project_id,
            payload={"field_count": len(body.responses)},
        ),
    )

    await record_progress(
        session,
        project_id,
        "discovery",
        "Intake submitted",
        "Scope locked in — build pipeline is starting",
    )

    return _session_from_row(row)


async def _apply_intake_to_project(
    session: AsyncSession,
    project_id: UUID,
    project: ProjectRow,
    fields: list[IntakeField],
    responses: dict,
) -> None:
    """Convert intake answers into project description enrichment and notes."""
    lines = [f"# {project.name}", "", "## Refined specification", ""]
    for field in fields:
        val = responses.get(field.id, "")
        if isinstance(val, list):
            val = ", ".join(val)
        if val:
            lines.append(f"**{field.label}:** {val}")

    enriched = "\n".join(lines)
    project.description = enriched

    # Map key fields to typed notes for agents
    legacy_mappings = {
        "must_have_features": NoteType.FEATURE,
        "gaps_to_address": NoteType.FEATURE,
        "what_works_today": NoteType.SCOPE_OUT,
        "out_of_scope": NoteType.SCOPE_OUT,
        "success_criteria": NoteType.INSTRUCTION,
        "existing_code_approach": NoteType.INSTRUCTION,
        "anything_else": NoteType.GENERAL,
        "confirm_interpretation": NoteType.INSTRUCTION,
        "main_entities": NoteType.FEATURE,
        "key_metrics": NoteType.FEATURE,
        "external_integrations": NoteType.INSTRUCTION,
        "catalog_scope": NoteType.FEATURE,
        "content_types": NoteType.FEATURE,
        "preserve_existing": NoteType.SCOPE_OUT,
    }
    mapped_ids: set[str] = set()
    for field in fields:
        note_type = field.note_type or legacy_mappings.get(field.id)
        if not note_type:
            continue
        val = responses.get(field.id)
        if val and (not isinstance(val, str) or val.strip()):
            content = val if isinstance(val, str) else ", ".join(val)
            await add_note(session, project_id, ProjectNoteCreate(content=content, note_type=note_type))
            mapped_ids.add(field.id)

    # Instruction note with remaining intake summary
    summary_parts = []
    skip_in_summary = mapped_ids | {"must_have_features", "out_of_scope", "anything_else"}
    for field in fields:
        if field.id in skip_in_summary:
            continue
        val = responses.get(field.id, "")
        if isinstance(val, list):
            val = ", ".join(val)
        if val:
            summary_parts.append(f"{field.label}: {val}")
    if summary_parts:
        await add_note(
            session,
            project_id,
            ProjectNoteCreate(
                content="Intake answers:\n" + "\n".join(f"- {p}" for p in summary_parts),
                note_type=NoteType.INSTRUCTION,
            ),
        )


async def auto_submit_expired_intake(session: AsyncSession) -> int:
    """Auto-submit intake forms past expiry using field defaults."""
    now = datetime.utcnow()
    result = await session.execute(
        select(DiscoverySessionRow).where(
            DiscoverySessionRow.status == DiscoveryStatus.AWAITING_USER.value,
            DiscoverySessionRow.expires_at <= now,
        )
    )
    count = 0
    for row in result.scalars():
        fields = [IntakeField.model_validate(f) for f in row.form_fields]
        defaults: dict[str, str | list[str]] = {}
        for field in fields:
            if field.default is not None:
                defaults[field.id] = field.default
            elif field.options:
                defaults[field.id] = field.options[0]
            else:
                defaults[field.id] = "Not specified (auto-submitted)"

        project = await session.get(ProjectRow, row.project_id)
        if not project:
            continue

        row.responses = defaults
        row.status = DiscoveryStatus.AUTO_SUBMITTED.value
        row.submitted_at = now
        project.state = ProjectState.PLANNING.value
        project.updated_at = now

        await _apply_intake_to_project(session, row.project_id, project, fields, defaults)
        workspace.write_artifact(
            row.project_id, "intake-responses.json", json.dumps(defaults, indent=2)
        )
        await session.commit()
        count += 1
        from app.services.pipeline_launcher import schedule_pipeline

        schedule_pipeline(row.project_id)
        logger.info("Auto-submitted intake for project %s", row.project_id)

    return count
