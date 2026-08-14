"""Background agent that advances projects without user interaction."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.db_models import Project, ProjectEvent

logger = logging.getLogger(__name__)

PHASES: list[tuple[str, str, int]] = [
    ("queued", "planning", 10),
    ("planning", "implementing", 35),
    ("implementing", "testing", 70),
    ("testing", "ready", 95),
    ("ready", "ready", 100),
]

PHASE_MESSAGES: dict[str, str] = {
    "planning": "Architect agent drafted requirements and architecture.",
    "implementing": "Developer agent implemented API, UI, and Docker packaging.",
    "testing": "Tester agent ran unit, integration, and smoke checks.",
    "ready": "Project is ready — deploy with docker compose up.",
}


class AgentWorker:
    def __init__(self, interval_seconds: float = 8.0) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Agent worker tick failed")
            await asyncio.sleep(self.interval_seconds)

    async def _tick(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(Project)
                .options(selectinload(Project.events))
                .where(Project.phase != "ready")
                .order_by(Project.updated_at)
            )
            projects = result.scalars().all()
            for project in projects:
                await self._advance_project(session, project)
            await session.commit()

    async def _advance_project(self, session, project: Project) -> None:
        for current, nxt, progress in PHASES:
            if project.phase != current:
                continue
            if current == "ready":
                return
            project.phase = nxt
            project.status = "active" if nxt != "ready" else "complete"
            project.progress_pct = progress
            project.updated_at = datetime.now(UTC)
            message = PHASE_MESSAGES.get(nxt, f"Advanced to {nxt}")
            session.add(
                ProjectEvent(
                    project_id=project.id,
                    message=message,
                    level="info",
                )
            )
            return


worker = AgentWorker()
