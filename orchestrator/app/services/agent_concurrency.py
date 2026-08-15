"""Resolve safe parallel agent limits from Cursor subscription usage and factory settings."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.cursor_client import CursorApiError, CursorClient
from app.services.cursor_connection import get_api_key
from app.services.factory_settings import (
    get_agent_backend,
    get_cursor_concurrent_limit,
    get_max_parallel_agents,
)

logger = logging.getLogger(__name__)

# Agent lifecycle statuses that do NOT consume a concurrent slot.
_AGENT_IDLE_STATUSES = frozenset(
    {
        "ACTIVE",  # Cursor marks idle agents ACTIVE — not the same as running
        "ARCHIVED",
        "IDLE",
        "COMPLETED",
        "FINISHED",
        "STOPPED",
        "DONE",
    }
)

_TERMINAL_AGENT_STATUSES = frozenset(
    {
        "FINISHED",
        "ERROR",
        "CANCELLED",
        "CANCELED",
        "EXPIRED",
        "COMPLETED",
        "FAILED",
        "ARCHIVED",
        "STOPPED",
        "DONE",
    }
)

_RUNNING_AGENT_STATUSES = frozenset(
    {
        "RUNNING",
        "CREATING",
        "PENDING",
        "IN_PROGRESS",
        "QUEUED",
        "STARTING",
        "WORKING",
        "INITIALIZING",
    }
)

_TERMINAL_RUN_STATUSES = frozenset(
    {
        "FINISHED",
        "ERROR",
        "CANCELLED",
        "CANCELED",
        "EXPIRED",
        "COMPLETED",
        "FAILED",
        "STOPPED",
        "DONE",
    }
)

_ACTIVE_CACHE_TTL_SECONDS = 20.0
_active_cache: dict[str, object] = {"fetched_at": 0.0, "count": 0, "running_agents": []}


@dataclass
class ConcurrencyBudget:
    max_parallel: int
    active_cursor_agents: int
    cursor_slot_limit: int
    available_cursor_slots: int
    backend: str
    strategy: str
    factory_cap: int
    idle_agents: int = 0


def invalidate_active_agent_cache() -> None:
    _active_cache["fetched_at"] = 0.0


def _latest_run_status(agent: dict) -> str:
    latest = agent.get("latestRun") or agent.get("latest_run") or {}
    if isinstance(latest, dict):
        return (latest.get("status") or "").upper()
    return (agent.get("latestRunStatus") or agent.get("runStatus") or "").upper()


def agent_consumes_cursor_slot(agent: dict) -> bool:
    """True only when an agent is actively executing — not idle ACTIVE shells."""
    run_status = _latest_run_status(agent)
    if run_status:
        return run_status not in _TERMINAL_RUN_STATUSES

    agent_status = (agent.get("status") or "").upper().strip()
    if not agent_status:
        return False
    if agent_status in _AGENT_IDLE_STATUSES or agent_status in _TERMINAL_AGENT_STATUSES:
        return False

    return agent_status in _RUNNING_AGENT_STATUSES


def _is_active_agent_status(status: str | None) -> bool:
    """Backward-compatible helper used in tests."""
    return agent_consumes_cursor_slot({"status": status or ""})


async def count_active_cursor_agents(api_key: str) -> tuple[int, int, list[str]]:
    """Return (running_count, idle_active_count, running_names)."""
    now = time.monotonic()
    if now - float(_active_cache["fetched_at"]) < _ACTIVE_CACHE_TTL_SECONDS:
        return (
            int(_active_cache["count"]),
            int(_active_cache.get("idle", 0)),
            list(_active_cache.get("running_agents") or []),
        )

    async with CursorClient(api_key) as client:
        agents, _ = await client.list_agents_page(limit=100, include_archived=False)

    running = 0
    idle_active = 0
    running_names: list[str] = []
    for agent in agents:
        status = (agent.get("status") or "").upper()
        name = agent.get("name") or agent.get("id") or "agent"
        if agent_consumes_cursor_slot(agent):
            running += 1
            running_names.append(name)
        elif status == "ACTIVE":
            idle_active += 1

    _active_cache["fetched_at"] = now
    _active_cache["count"] = running
    _active_cache["idle"] = idle_active
    _active_cache["running_agents"] = running_names
    return running, idle_active, running_names


async def resolve_concurrency_budget(session: AsyncSession) -> ConcurrencyBudget:
    backend = await get_agent_backend(session)
    factory_cap = await get_max_parallel_agents(session)

    if backend == "local":
        cap = min(factory_cap, 6)
        return ConcurrencyBudget(
            max_parallel=cap,
            active_cursor_agents=0,
            cursor_slot_limit=0,
            available_cursor_slots=cap,
            backend=backend,
            factory_cap=factory_cap,
            strategy="Local scaffold mode — parallel in-process work capped for stability.",
        )

    if backend == "cursor_local":
        cap = min(factory_cap, 3)
        return ConcurrencyBudget(
            max_parallel=cap,
            active_cursor_agents=0,
            cursor_slot_limit=0,
            available_cursor_slots=cap,
            backend=backend,
            factory_cap=factory_cap,
            strategy="Cursor local agents — limited parallelism to avoid overloading the host.",
        )

    cursor_limit = await get_cursor_concurrent_limit(session)
    headroom = settings.cursor_agent_headroom
    active = 0
    idle_active = 0

    api_key = await get_api_key(session)
    if api_key:
        try:
            active, idle_active, _ = await count_active_cursor_agents(api_key)
        except CursorApiError as exc:
            logger.warning("Could not count active Cursor agents: %s", exc.message)

    available = cursor_limit - active - headroom
    max_parallel = max(0, min(factory_cap, available))

    if max_parallel == 0:
        strategy = (
            f"Cursor Cloud: {active} agent run(s) in progress"
            f"{f' ({idle_active} idle Cursor agent(s) parked, not using slots)' if idle_active else ''}. "
            f"No factory slots free (limit {cursor_limit}, {headroom} reserved for manual use). "
            "The factory will wait before starting new cloud agents."
        )
    else:
        strategy = (
            f"Cursor Cloud: {active} running agent run(s)"
            f"{f' · {idle_active} idle Cursor agent(s) parked (not using slots)' if idle_active else ''}; "
            f"up to {max_parallel} parallel factory agent(s) "
            f"(limit {cursor_limit}, {headroom} slot(s) reserved for manual use)."
        )

    return ConcurrencyBudget(
        max_parallel=max_parallel,
        active_cursor_agents=active,
        cursor_slot_limit=cursor_limit,
        available_cursor_slots=max(0, available),
        backend=backend,
        factory_cap=factory_cap,
        strategy=strategy,
        idle_agents=idle_active,
    )


async def reclaim_idle_factory_agents(api_key: str, *, keep_recent: int = 3) -> int:
    """Archive finished factory-* cloud agents so account caps do not block new creates."""
    archived = 0
    idle_factory: list[dict] = []
    max_archive_per_call = 15
    consecutive_failures = 0
    async with CursorClient(api_key) as client:
        cursor: str | None = None
        for _ in range(8):
            items, cursor = await client.list_agents_page(
                limit=100, cursor=cursor, include_archived=False
            )
            for agent in items:
                name = str(agent.get("name") or "")
                if not name.startswith("factory-"):
                    continue
                if agent_consumes_cursor_slot(agent):
                    continue
                idle_factory.append(agent)
            if not cursor:
                break
        for agent in idle_factory[max(0, keep_recent) :]:
            if archived >= max_archive_per_call:
                break
            agent_id = agent.get("id")
            if not agent_id:
                continue
            try:
                await client.archive_agent(str(agent_id))
                archived += 1
                consecutive_failures = 0
            except CursorApiError as exc:
                consecutive_failures += 1
                logger.warning("Could not archive idle factory agent %s: %s", agent_id, exc.message)
                if consecutive_failures >= 3:
                    break
    if archived:
        invalidate_active_agent_cache()
    return archived


async def wait_for_cursor_capacity(
    session: AsyncSession,
    *,
    min_slots: int = 1,
    timeout_seconds: float = 900,
    poll_seconds: float = 20,
) -> ConcurrencyBudget:
    """Block until at least min_slots factory parallel capacity is available."""
    deadline = time.monotonic() + timeout_seconds
    last: ConcurrencyBudget | None = None
    while time.monotonic() < deadline:
        invalidate_active_agent_cache()
        last = await resolve_concurrency_budget(session)
        if last.max_parallel >= min_slots:
            return last
        await asyncio.sleep(poll_seconds)
    return last or await resolve_concurrency_budget(session)


def concurrency_budget_to_dict(budget: ConcurrencyBudget) -> dict:
    return {
        "max_parallel": budget.max_parallel,
        "active_cursor_agents": budget.active_cursor_agents,
        "cursor_slot_limit": budget.cursor_slot_limit,
        "available_cursor_slots": budget.available_cursor_slots,
        "backend": budget.backend,
        "factory_cap": budget.factory_cap,
        "strategy": budget.strategy,
        "idle_agents": budget.idle_agents,
    }
