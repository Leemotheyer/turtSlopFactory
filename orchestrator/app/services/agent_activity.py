"""Aggregate agent visibility data for the dashboard."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import EventRow, ProgressEntryRow, TaskRow
from app.models import EventType, TaskStatus
from app.workspace.manager import WorkspaceManager

_AGENT_EVENT_TYPES = {
    EventType.AGENT_COMMAND_STARTED.value,
    EventType.AGENT_COMMAND_OUTPUT.value,
    EventType.AGENT_COMMAND_FINISHED.value,
    EventType.TASK_STATUS_CHANGED.value,
    EventType.PROGRESS_UPDATED.value,
    EventType.PIPELINE_STOPPED.value,
}

workspace = WorkspaceManager()


def _is_cursor_cloud_agent_id(agent_id: str) -> bool:
    return agent_id.startswith("bc-")


def _cursor_url(agent_id: str | None, explicit_url: str | None = None) -> str | None:
    if explicit_url and explicit_url.startswith("http"):
        return explicit_url
    if not agent_id:
        return None
    if agent_id.startswith(("cursor_local", "cursor_cloud", "local")):
        return None
    if agent_id.startswith("http"):
        return agent_id
    if agent_id.startswith(("architect-", "developer-", "reviewer-", "tester-")):
        return None
    if not _is_cursor_cloud_agent_id(agent_id):
        return None
    return f"https://cursor.com/agents/{agent_id}"


def _remember_task_agent(
    agent_ids_by_task: dict[str, str],
    cursor_urls_by_task: dict[str, str],
    task_id: str,
    agent_id: str | None,
    *,
    cursor_url: str | None = None,
) -> None:
    """Prefer real Cursor cloud agent ids over placeholder role-task ids."""
    if cursor_url and cursor_url.startswith("http"):
        cursor_urls_by_task[task_id] = cursor_url
    if not agent_id:
        return
    existing = agent_ids_by_task.get(task_id)
    if _is_cursor_cloud_agent_id(agent_id):
        agent_ids_by_task[task_id] = agent_id
        cursor_urls_by_task.setdefault(task_id, cursor_url or f"https://cursor.com/agents/{agent_id}")
    elif not existing or not _is_cursor_cloud_agent_id(existing):
        agent_ids_by_task[task_id] = agent_id


async def get_agent_activity(
    session: AsyncSession,
    project_id: UUID,
    *,
    pipeline_running: bool,
    stop_requested: bool,
    current_state: str,
) -> dict:
    task_result = await session.execute(
        select(TaskRow)
        .where(TaskRow.project_id == project_id)
        .order_by(TaskRow.created_at.desc())
        .limit(50)
    )
    tasks = list(task_result.scalars())

    event_result = await session.execute(
        select(EventRow)
        .where(
            EventRow.project_id == project_id,
            EventRow.type.in_(_AGENT_EVENT_TYPES),
        )
        .order_by(EventRow.created_at.desc())
        .limit(200)
    )
    events = list(reversed(event_result.scalars().all()))

    progress_result = await session.execute(
        select(ProgressEntryRow)
        .where(ProgressEntryRow.project_id == project_id)
        .order_by(ProgressEntryRow.created_at.desc())
        .limit(15)
    )
    progress_entries = list(reversed(progress_result.scalars().all()))

    outputs_by_task: dict[str, str] = {}
    agent_ids_by_task: dict[str, str] = {}
    cursor_urls_by_task: dict[str, str] = {}
    for ev in events:
        tid = str(ev.task_id) if ev.task_id else None
        payload = ev.payload if isinstance(ev.payload, dict) else {}
        if tid and ev.type == EventType.AGENT_COMMAND_FINISHED.value:
            outputs_by_task[tid] = str(payload.get("output") or "")
        if tid:
            _remember_task_agent(
                agent_ids_by_task,
                cursor_urls_by_task,
                tid,
                ev.agent_id,
                cursor_url=str(payload["cursor_url"]) if payload.get("cursor_url") else None,
            )

    meta = workspace.load_metadata(project_id)
    live_agents = meta.get("live_agents") or {}

    active_tasks = []
    for task in tasks:
        if task.status != TaskStatus.RUNNING.value:
            continue
        tid = str(task.id)
        agent_id = agent_ids_by_task.get(tid)
        live = next(
            (v for v in live_agents.values() if v.get("task_id") == tid or v.get("role") == task.role),
            {},
        )
        active_tasks.append(
            {
                "task_id": tid,
                "title": task.title,
                "description": task.description[:500],
                "role": task.role,
                "status": task.status,
                "started_at": task.created_at.isoformat(),
                "agent_id": live.get("agent_id") or agent_id,
                "cursor_url": _cursor_url(
                    live.get("agent_id") or agent_id,
                    live.get("cursor_url") or cursor_urls_by_task.get(tid),
                ),
                "live_status": live.get("status"),
                "live_detail": live.get("detail"),
            }
        )

    recent_tasks = []
    for task in tasks[:20]:
        tid = str(task.id)
        live = next((v for v in live_agents.values() if v.get("task_id") == tid), {})
        agent_id = live.get("agent_id") or agent_ids_by_task.get(tid)
        explicit_url = live.get("cursor_url") or cursor_urls_by_task.get(tid)
        recent_tasks.append(
            {
                "task_id": tid,
                "title": task.title,
                "description": task.description[:500],
                "role": task.role,
                "status": task.status,
                "started_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
                "output_preview": (outputs_by_task.get(tid) or "")[:500] or None,
                "agent_id": agent_id,
                "cursor_url": _cursor_url(agent_id, explicit_url),
            }
        )

    activity_feed = []
    for ev in events[-40:]:
        payload = ev.payload or {}
        activity_feed.append(
            {
                "id": str(ev.id),
                "type": ev.type,
                "task_id": str(ev.task_id) if ev.task_id else None,
                "agent_id": ev.agent_id,
                "created_at": ev.created_at.isoformat(),
                "summary": _summarize_event(ev.type, payload),
                "detail": _event_detail(ev.type, payload),
                "cursor_url": _cursor_url(
                    ev.agent_id,
                    (payload.get("cursor_url") if isinstance(payload, dict) else None)
                    or (cursor_urls_by_task.get(str(ev.task_id)) if ev.task_id else None),
                ),
            }
        )

    log_path = workspace.logs_dir(project_id) / "pipeline.log"
    log_tail = ""
    if log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()
        log_tail = "\n".join(lines[-40:])

    return {
        "project_id": str(project_id),
        "current_state": current_state,
        "pipeline_running": pipeline_running,
        "stop_requested": stop_requested,
        "active_agents": active_tasks,
        "live_agents": list(live_agents.values()),
        "recent_tasks": recent_tasks,
        "activity_feed": activity_feed,
        "progress_entries": [
            {
                "id": str(p.id),
                "category": p.category,
                "title": p.title,
                "summary": p.summary,
                "detail": p.detail,
                "created_at": p.created_at.isoformat(),
            }
            for p in progress_entries
        ],
        "pipeline_log_tail": log_tail,
    }


def _summarize_event(event_type: str, payload: dict) -> str:
    if event_type == EventType.AGENT_COMMAND_STARTED.value:
        role = payload.get("role") or "agent"
        title = payload.get("title") or payload.get("command") or "task"
        return f"{role} started: {title}"
    if event_type == EventType.AGENT_COMMAND_OUTPUT.value:
        role = payload.get("role") or "agent"
        status = payload.get("status") or "working"
        return f"{role} — {status}"
    if event_type == EventType.AGENT_COMMAND_FINISHED.value:
        ok = payload.get("success", True)
        return "Agent finished" if ok else "Agent failed"
    if event_type == EventType.TASK_STATUS_CHANGED.value:
        return str(payload.get("title") or payload.get("status") or "Task updated")
    if event_type == EventType.PROGRESS_UPDATED.value:
        return f"{payload.get('title')}: {payload.get('summary')}"
    if event_type == EventType.PIPELINE_STOPPED.value:
        return "Pipeline stopped"
    return str(payload)[:120]


def _event_detail(event_type: str, payload: dict) -> str | None:
    if event_type == EventType.AGENT_COMMAND_OUTPUT.value:
        detail = payload.get("detail")
        return str(detail)[:2000] if detail else None
    if event_type == EventType.AGENT_COMMAND_FINISHED.value:
        output = payload.get("output")
        return str(output)[:2000] if output else None
    if event_type == EventType.AGENT_COMMAND_STARTED.value:
        desc = payload.get("description")
        return str(desc)[:2000] if desc else None
    if event_type == EventType.PROGRESS_UPDATED.value:
        return str(payload.get("summary") or "")[:500] or None
    return None
