"""Resolve safe parallel agent limits from Cursor subscription usage and factory settings."""

from __future__ import annotations

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

_ACTIVE_CACHE_TTL_SECONDS = 20.0
_active_cache: dict[str, object] = {"fetched_at": 0.0, "count": 0}


@dataclass
class ConcurrencyBudget:
    max_parallel: int
    active_cursor_agents: int
    cursor_slot_limit: int
    available_cursor_slots: int
    backend: str
    strategy: str
    factory_cap: int


def _is_active_agent_status(status: str | None) -> bool:
    normalized = (status or "").upper().strip()
    if not normalized:
        return False
    return normalized not in _TERMINAL_AGENT_STATUSES


async def count_active_cursor_agents(api_key: str) -> int:
    now = time.monotonic()
    if now - float(_active_cache["fetched_at"]) < _ACTIVE_CACHE_TTL_SECONDS:
        return int(_active_cache["count"])

    async with CursorClient(api_key) as client:
        agents = await client.list_agents(limit=100)

    active = sum(1 for agent in agents if _is_active_agent_status(agent.get("status")))
    _active_cache["fetched_at"] = now
    _active_cache["count"] = active
    return active


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

    api_key = await get_api_key(session)
    if api_key:
        try:
            active = await count_active_cursor_agents(api_key)
        except CursorApiError as exc:
            logger.warning("Could not count active Cursor agents: %s", exc.message)

    available = max(1, cursor_limit - active - headroom)
    max_parallel = max(1, min(factory_cap, available))

    strategy = (
        f"Cursor Cloud: {active} active agent(s) on your account; "
        f"using up to {max_parallel} parallel factory agent(s) "
        f"(limit {cursor_limit}, {headroom} slot(s) reserved for manual use)."
    )
    return ConcurrencyBudget(
        max_parallel=max_parallel,
        active_cursor_agents=active,
        cursor_slot_limit=cursor_limit,
        available_cursor_slots=available,
        backend=backend,
        factory_cap=factory_cap,
        strategy=strategy,
    )


def concurrency_budget_to_dict(budget: ConcurrencyBudget) -> dict:
    return {
        "max_parallel": budget.max_parallel,
        "active_cursor_agents": budget.active_cursor_agents,
        "cursor_slot_limit": budget.cursor_slot_limit,
        "available_cursor_slots": budget.available_cursor_slots,
        "backend": budget.backend,
        "factory_cap": budget.factory_cap,
        "strategy": budget.strategy,
    }
