"""Post-production self-propelling development cycles."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import ProjectRow
from app.models import ProjectState
from app.services.pipeline_control import is_pipeline_paused
from app.workspace.manager import WorkspaceManager

logger = logging.getLogger(__name__)


def _config(meta: dict) -> dict[str, Any]:
    raw = meta.get("self_propelling") or {}
    if not isinstance(raw, dict):
        raw = {}
    return raw


def is_self_propelling_enabled(project_id: UUID, workspace: WorkspaceManager | None = None) -> bool:
    ws = workspace or WorkspaceManager()
    return bool(_config(ws.load_metadata(project_id)).get("enabled"))


def get_self_propelling_settings(
    project_id: UUID, workspace: WorkspaceManager | None = None
) -> dict[str, Any]:
    ws = workspace or WorkspaceManager()
    meta = ws.load_metadata(project_id)
    cfg = _config(meta)
    return {
        "enabled": bool(cfg.get("enabled")),
        "post_production_passes": cfg.get("post_production_passes"),
        "interval_hours": cfg.get("interval_hours"),
        "token_budget_per_cycle": cfg.get("token_budget_per_cycle"),
        "cycles_completed": int(cfg.get("cycles_completed") or 0),
        "last_cycle_at": cfg.get("last_cycle_at"),
        "next_cycle_at": cfg.get("next_cycle_at"),
        "last_audit_fingerprint": cfg.get("last_audit_fingerprint"),
        "cycle_start_tokens": cfg.get("cycle_start_tokens"),
        "factory_defaults": {
            "post_production_passes": settings.post_production_enrichment_passes,
            "interval_hours": settings.post_production_interval_hours,
            "token_budget_per_cycle": settings.default_token_budget_per_cycle,
        },
    }


def save_self_propelling_settings(
    project_id: UUID,
    *,
    enabled: bool | None = None,
    post_production_passes: int | None = None,
    interval_hours: int | None = None,
    token_budget_per_cycle: int | None = None,
    workspace: WorkspaceManager | None = None,
) -> dict[str, Any]:
    ws = workspace or WorkspaceManager()
    meta = ws.load_metadata(project_id)
    cfg = _config(meta)

    if enabled is not None:
        cfg["enabled"] = enabled
    if post_production_passes is not None:
        cfg["post_production_passes"] = post_production_passes
    if interval_hours is not None:
        cfg["interval_hours"] = interval_hours
    if token_budget_per_cycle is not None:
        cfg["token_budget_per_cycle"] = token_budget_per_cycle

    meta["self_propelling"] = cfg
    ws.save_metadata(project_id, meta)
    return get_self_propelling_settings(project_id, ws)


def resolve_post_production_passes(project_id: UUID, workspace: WorkspaceManager | None = None) -> int:
    cfg = get_self_propelling_settings(project_id, workspace)
    passes = cfg.get("post_production_passes")
    if passes is not None:
        return max(0, min(int(passes), 10))
    return settings.post_production_enrichment_passes


def resolve_interval_hours(project_id: UUID, workspace: WorkspaceManager | None = None) -> int:
    cfg = get_self_propelling_settings(project_id, workspace)
    hours = cfg.get("interval_hours")
    if hours is not None:
        return max(1, min(int(hours), 168))
    return settings.post_production_interval_hours


def resolve_token_budget(project_id: UUID, workspace: WorkspaceManager | None = None) -> int | None:
    cfg = get_self_propelling_settings(project_id, workspace)
    budget = cfg.get("token_budget_per_cycle")
    if budget is not None:
        value = int(budget)
        return value if value > 0 else None
    default = settings.default_token_budget_per_cycle
    return default if default and default > 0 else None


def audit_fingerprint(audit: dict) -> str:
    """Stable hash of audit signals — skip architect when unchanged."""
    payload = {
        "health_ok": audit.get("health_ok"),
        "has_html_ui": audit.get("has_html_ui"),
        "mobile_friendly": audit.get("mobile_friendly"),
        "issues": sorted(str(i) for i in (audit.get("issues") or [])),
        "endpoint_paths": sorted(
            e.get("path") for e in (audit.get("endpoints") or []) if e.get("ok")
        ),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def should_skip_architect(project_id: UUID, audit: dict, workspace: WorkspaceManager) -> bool:
    """Token optimization: reuse local plan when preview audit unchanged."""
    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    previous = cfg.get("last_audit_fingerprint")
    current = audit_fingerprint(audit)
    return bool(previous and previous == current)


def record_audit_fingerprint(project_id: UUID, audit: dict, workspace: WorkspaceManager) -> None:
    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    cfg["last_audit_fingerprint"] = audit_fingerprint(audit)
    meta["self_propelling"] = cfg
    workspace.save_metadata(project_id, meta)


def mark_cycle_started(
    project_id: UUID,
    workspace: WorkspaceManager,
    *,
    cycle_start_tokens: int | None = None,
) -> None:
    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    cfg["cycle_started_at"] = datetime.utcnow().isoformat()
    if cycle_start_tokens is not None:
        cfg["cycle_start_tokens"] = cycle_start_tokens
    meta["self_propelling"] = cfg
    workspace.save_metadata(project_id, meta)


def mark_cycle_completed(project_id: UUID, workspace: WorkspaceManager) -> None:
    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    cfg["cycles_completed"] = int(cfg.get("cycles_completed") or 0) + 1
    cfg["last_cycle_at"] = datetime.utcnow().isoformat()
    interval = resolve_interval_hours(project_id, workspace)
    cfg["next_cycle_at"] = (datetime.utcnow() + timedelta(hours=interval)).isoformat()
    cfg.pop("cycle_started_at", None)
    cfg.pop("cycle_start_tokens", None)
    meta["self_propelling"] = cfg
    workspace.save_metadata(project_id, meta)


async def check_token_budget(
    session: AsyncSession,
    project_id: UUID,
    workspace: WorkspaceManager,
) -> tuple[bool, str]:
    """Return (ok, message). Blocks cycle when per-cycle token budget exceeded."""
    budget = resolve_token_budget(project_id, workspace)
    if not budget:
        return True, "no budget cap"

    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    cycle_start = cfg.get("cycle_start_tokens")
    if cycle_start is None:
        return True, "cycle not metered"

    from app.services.cursor_connection import fetch_usage

    usage = await fetch_usage(session)
    if not usage.get("connected"):
        return True, "cursor not connected — skip budget check"

    tokens = (usage.get("tokens") or {}).get("total_tokens")
    if tokens is None:
        return True, "usage unavailable"

    consumed = max(0, int(tokens) - int(cycle_start))
    if consumed >= budget:
        return False, f"Token budget exceeded ({consumed:,} / {budget:,} this cycle)"
    return True, f"{consumed:,} / {budget:,} tokens this cycle"


def is_due_for_post_production(project_id: UUID, workspace: WorkspaceManager) -> bool:
    if not is_self_propelling_enabled(project_id, workspace):
        return False
    meta = workspace.load_metadata(project_id)
    cfg = _config(meta)
    next_at = cfg.get("next_cycle_at")
    if not next_at:
        return True
    try:
        due = datetime.fromisoformat(str(next_at))
    except ValueError:
        return True
    return datetime.utcnow() >= due


async def maybe_schedule_post_production(
    session: AsyncSession,
    project_id: UUID,
    *,
    force: bool = False,
) -> bool:
    """Schedule a post-production improvement cycle."""
    from app.pipeline.executor import pipeline_executor

    row = await session.get(ProjectRow, project_id)
    if not row or row.state != ProjectState.PRODUCTION.value:
        return False
    if not is_self_propelling_enabled(project_id):
        return False
    if pipeline_executor.is_running(project_id):
        return False
    if is_pipeline_paused(project_id):
        logger.info("Skipping post-production cycle for %s — pipeline paused", project_id)
        return False
    if not force and not is_due_for_post_production(project_id, WorkspaceManager()):
        return False

    workspace = WorkspaceManager()
    meta = workspace.load_metadata(project_id)
    meta["post_production_pending"] = True
    workspace.save_metadata(project_id, meta)

    from app.services.pipeline_launcher import schedule_pipeline

    started = schedule_pipeline(project_id, force=True)
    if started:
        logger.info("Scheduled post-production cycle for project %s", project_id)
    return started


async def scan_due_post_production_projects(session: AsyncSession) -> int:
    """Background scheduler: start due post-production cycles."""
    result = await session.execute(
        select(ProjectRow).where(ProjectRow.state == ProjectState.PRODUCTION.value)
    )
    scheduled = 0
    workspace = WorkspaceManager()
    for row in result.scalars():
        if not is_self_propelling_enabled(row.id, workspace):
            continue
        if not is_due_for_post_production(row.id, workspace):
            continue
        if await maybe_schedule_post_production(session, row.id):
            scheduled += 1
    return scheduled
