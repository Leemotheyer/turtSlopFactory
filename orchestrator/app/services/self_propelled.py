"""Self-propelled development: autonomous iteration after each successful review."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import ProjectRow
from app.events import event_bus
from app.models import (
    EventType,
    FactoryEvent,
    NoteType,
    NotificationType,
    ProjectNoteCreate,
    ProjectState,
)
from app.services.improvement_planner import Improvement, plan_improvements
from app.services.notes import add_note, list_notes
from app.services.notifications import create_notification
from app.services.progress import record_progress
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)

META_KEY = "self_propelled"


def _default_meta() -> dict:
    return {
        "enabled": settings.self_propelled_enabled,
        "iteration": 0,
        "max_iterations": settings.max_self_propelled_iterations,
        "last_improvements": [],
        "paused_reason": None,
    }


def get_self_propelled_meta(metadata: dict) -> dict:
    stored = metadata.get(META_KEY) or {}
    base = _default_meta()
    base.update({k: v for k, v in stored.items() if v is not None})
    return base


def save_self_propelled_meta(metadata: dict, sp: dict) -> dict:
    metadata[META_KEY] = sp
    return metadata


def is_self_propelled_enabled(metadata: dict) -> bool:
    return bool(get_self_propelled_meta(metadata).get("enabled", True))


def get_iteration(metadata: dict) -> int:
    return int(get_self_propelled_meta(metadata).get("iteration", 0))


def set_self_propelled_enabled(
    workspace: WorkspaceManager, project_id: UUID, enabled: bool
) -> dict:
    meta = workspace.load_metadata(project_id)
    sp = get_self_propelled_meta(meta)
    sp["enabled"] = enabled
    if enabled:
        sp["paused_reason"] = None
    save_self_propelled_meta(meta, sp)
    workspace.save_metadata(project_id, meta)
    return sp


async def plan_and_apply_improvements(
    session: AsyncSession,
    workspace: WorkspaceManager,
    project: ProjectRow,
    context: dict,
    *,
    max_items: int | None = None,
) -> tuple[list[Improvement], dict]:
    """
    Generate improvements for the next iteration and persist them as feature notes.

    Returns (improvements, updated self_propelled metadata).
    """
    meta = workspace.load_metadata(project.id)
    sp = get_self_propelled_meta(meta)
    iteration = int(sp.get("iteration", 0)) + 1

    notes = await list_notes(session, project.id)
    note_dicts = [{"type": n.note_type.value, "content": n.content} for n in notes]
    review_raw = workspace.read_artifact(project.id, "review.json")

    improvements = plan_improvements(
        description=project.description,
        notes=note_dicts,
        iteration=iteration,
        review_artifact=review_raw,
        max_items=max_items or settings.self_propelled_improvements_per_iteration,
    )

    applied: list[dict] = []
    for item in improvements:
        note = await add_note(
            session,
            project.id,
            ProjectNoteCreate(
                content=f"[Iteration {iteration}] {item.description}",
                note_type=NoteType.FEATURE,
            ),
        )
        applied.append(
            {
                "title": item.title,
                "description": item.description,
                "category": item.category,
                "note_id": str(note.id),
            }
        )

    sp["iteration"] = iteration
    sp["last_improvements"] = applied
    sp["last_iteration_at"] = datetime.utcnow().isoformat()
    save_self_propelled_meta(meta, sp)
    workspace.save_metadata(project.id, meta)

    if applied:
        workspace.write_artifact(
            project.id,
            f"improvements-iteration-{iteration}.json",
            json.dumps(applied, indent=2),
        )
        workspace.append_log(
            project.id,
            "pipeline.log",
            f"[self-propelled] Iteration {iteration}: queued {len(applied)} improvement(s)",
        )

    return improvements, sp


def should_continue_iterating(
    metadata: dict,
    project_state: ProjectState,
) -> tuple[bool, str | None]:
    """Decide whether to enqueue another autonomous iteration."""
    if project_state == ProjectState.PRODUCTION:
        return False, "production"
    if project_state == ProjectState.AUTONOMOUSLY_BLOCKED:
        return False, "blocked"

    sp = get_self_propelled_meta(metadata)
    if not sp.get("enabled", True):
        return False, "disabled"

    iteration = int(sp.get("iteration", 0))
    max_iter = int(sp.get("max_iterations", settings.max_self_propelled_iterations))
    if iteration >= max_iter:
        return False, "max_iterations"

    return True, None


async def start_next_iteration(
    session: AsyncSession,
    workspace: WorkspaceManager,
    project: ProjectRow,
    context: dict,
) -> bool:
    """
    Plan improvements and prepare project for another implementation cycle.

    Returns True if a new iteration was started, False if iteration should stop.
    """
    meta = workspace.load_metadata(project.id)
    can_continue, reason = should_continue_iterating(meta, ProjectState(project.state))
    if not can_continue:
        sp = get_self_propelled_meta(meta)
        sp["paused_reason"] = reason
        save_self_propelled_meta(meta, sp)
        workspace.save_metadata(project.id, meta)
        if reason == "max_iterations":
            await record_progress(
                session,
                project.id,
                "iteration",
                "Self-propelled development paused",
                f"Reached {sp.get('iteration', 0)} iteration(s) — promote to production or re-enable to continue.",
            )
            await create_notification(
                session,
                project.id,
                NotificationType.ITERATION_PAUSED,
                "Autonomous iterations complete",
                (
                    f"{project.name} finished {sp.get('iteration', 0)} improvement cycle(s). "
                    "Review the live preview and promote when ready."
                ),
                action="overview",
            )
        return False

    improvements, sp = await plan_and_apply_improvements(session, workspace, project, context)
    if not improvements:
        sp["paused_reason"] = "no_improvements"
        save_self_propelled_meta(meta, sp)
        workspace.save_metadata(project.id, meta)
        await record_progress(
            session,
            project.id,
            "iteration",
            "Self-propelled development complete",
            "No further improvements identified — ready for production.",
        )
        await create_notification(
            session,
            project.id,
            NotificationType.REVIEW_READY,
            "Ready for production",
            f"{project.name} passed all improvement cycles. Promote to production when ready.",
            action="overview",
        )
        return False

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.ITERATION_STARTED,
            project_id=project.id,
            payload={
                "iteration": sp["iteration"],
                "improvements": [i.title for i in improvements],
            },
        ),
    )

    await record_progress(
        session,
        project.id,
        "iteration",
        f"Iteration {sp['iteration']} started",
        "; ".join(i.title for i in improvements),
        detail="\n".join(f"- {i.description}" for i in improvements),
    )

    await create_notification(
        session,
        project.id,
        NotificationType.ITERATION_UPDATE,
        f"Iteration {sp['iteration']} in progress",
        f"Agents are implementing: {', '.join(i.title for i in improvements)}",
        action="overview",
    )

    return True
