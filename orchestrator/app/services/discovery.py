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
from app.services.notifications import create_notification
from app.services.notes import add_note
from app.services.progress import record_progress
from app.workspace.manager import WorkspaceManager

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


async def run_discovery(session: AsyncSession, project_id: UUID) -> DiscoverySession:
    project = await session.get(ProjectRow, project_id)
    if not project:
        raise ValueError("Project not found")

    existing = await get_discovery(session, project_id)
    if existing:
        if existing.status in (
            DiscoveryStatus.AWAITING_USER,
            DiscoveryStatus.SUBMITTED,
            DiscoveryStatus.AUTO_SUBMITTED,
        ):
            return existing
        if (
            existing.status == DiscoveryStatus.GENERATING
            and project.state not in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value)
        ):
            return existing

    if project.state not in (ProjectState.REQUESTED.value, ProjectState.DISCOVERY.value):
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

    # Simulate brief thinking delay for UX
    loose_plan, form_fields = generate_discovery(project.name, project.description)

    row.loose_plan = loose_plan
    row.form_fields = [f.model_dump() for f in form_fields]
    row.status = DiscoveryStatus.AWAITING_USER.value
    row.expires_at = datetime.utcnow() + timedelta(hours=settings.intake_form_timeout_hours)

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
        "Scope locked in — ready to start the build pipeline",
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
    mappings = {
        "must_have_features": NoteType.FEATURE,
        "out_of_scope": NoteType.SCOPE_OUT,
        "success_criteria": NoteType.INSTRUCTION,
        "anything_else": NoteType.GENERAL,
    }
    for field_id, note_type in mappings.items():
        val = responses.get(field_id)
        if val and (not isinstance(val, str) or val.strip()):
            content = val if isinstance(val, str) else ", ".join(val)
            await add_note(session, project_id, ProjectNoteCreate(content=content, note_type=note_type))

    # Instruction note with full intake summary
    summary_parts = []
    for field in fields:
        if field.id in ("must_have_features", "out_of_scope", "anything_else"):
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
        logger.info("Auto-submitted intake for project %s", row.project_id)

    return count
