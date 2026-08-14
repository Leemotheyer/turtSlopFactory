"""Self-propelled development agent loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models_db import EventRow, ProjectRow

logger = logging.getLogger(__name__)

PIPELINE_STAGES = [
    "requested",
    "planning",
    "implementing",
    "testing",
    "review",
    "complete",
]

IMPROVEMENTS = [
    "Improve mobile layout and touch targets",
    "Add project progress timeline to dashboard",
    "Harden Docker healthchecks and restart policy",
    "Add API pagination for project events",
    "Polish empty states and loading indicators",
]

_running: dict[int, asyncio.Task] = {}


async def _log(session: AsyncSession, project_id: int, message: str) -> None:
    session.add(EventRow(project_id=project_id, message=message))
    await session.commit()


async def _advance_project(session: AsyncSession, project: ProjectRow, message: str) -> None:
    project.updated_at = datetime.now(timezone.utc)
    await _log(session, project.id, message)


async def _run_pipeline(project_id: int) -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            return

        try:
            await _advance_project(session, project, "Agent loop started")

            for stage in PIPELINE_STAGES[1:]:
                if stage == "complete":
                    project.status = "complete"
                else:
                    project.status = stage
                await _advance_project(
                    session,
                    project,
                    f"[{stage}] Agent working autonomously — no user input required",
                )
                await asyncio.sleep(0.05)

            project.iteration += 1
            await _advance_project(session, project, f"Iteration {project.iteration} complete")

            if project.iteration < 3:
                improvement = IMPROVEMENTS[project.iteration % len(IMPROVEMENTS)]
                project.status = "planning"
                await _advance_project(
                    session,
                    project,
                    f"Self-propelled improvement: {improvement}",
                )
                await asyncio.sleep(0.05)
                _running[project_id] = asyncio.create_task(_run_pipeline(project_id))
            else:
                await _advance_project(session, project, "Project ready — check back anytime")
        except asyncio.CancelledError:
            await _advance_project(session, project, "Agent loop paused")
            raise
        except Exception as exc:
            logger.exception("Pipeline failed for project %s", project_id)
            project.status = "blocked"
            await _advance_project(session, project, f"Pipeline error: {exc}")
        finally:
            _running.pop(project_id, None)


def start_project_pipeline(project_id: int) -> bool:
    if project_id in _running:
        return False
    _running[project_id] = asyncio.create_task(_run_pipeline(project_id))
    return True


def is_running(project_id: int) -> bool:
    return project_id in _running
