"""Per-project development statistics derived from pipeline runs and tasks."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import DeploymentRow, PipelineRunRow, TaskRow
from app.models import ProjectState
from app.pipeline.executor import pipeline_executor
from app.services.pipeline_control import is_pipeline_paused
from app.services.self_propelling import get_self_propelling_settings
from app.workspace.manager import WorkspaceManager

# User-stopped runs are excluded from active development time.
_EXCLUDED_OUTCOMES = frozenset({"stopped"})


def _run_duration_seconds(run: PipelineRunRow, *, now: datetime | None = None) -> float:
    end = run.finished_at or now
    if end is None:
        return 0.0
    return max(0.0, (end - run.started_at).total_seconds())


def _counts_active_development_time(run: PipelineRunRow) -> bool:
    return run.outcome not in _EXCLUDED_OUTCOMES


async def compute_project_stats(
    session: AsyncSession,
    project_id: UUID,
    *,
    project_state: str | None = None,
    workspace: WorkspaceManager | None = None,
) -> dict:
    """Aggregate development stats for one project.

    Development time is the sum of finished pipeline run durations while agents
    were actively working. It excludes user-stopped runs and does not count
    idle time waiting in REVIEW for production approval (that gap has no run).
    """
    ws = workspace or WorkspaceManager()
    now = datetime.utcnow()

    result = await session.execute(
        select(PipelineRunRow)
        .where(PipelineRunRow.project_id == project_id)
        .order_by(PipelineRunRow.started_at.asc())
    )
    runs = list(result.scalars())

    finished = [r for r in runs if r.finished_at is not None]
    active_runs = [r for r in finished if _counts_active_development_time(r)]

    development_seconds = sum(_run_duration_seconds(r) for r in active_runs)

    pipeline_running = pipeline_executor.is_running(project_id)
    pipeline_paused = is_pipeline_paused(project_id)
    development_active = pipeline_running and not pipeline_paused

    if development_active:
        running_row = next((r for r in runs if r.finished_at is None), None)
        if running_row and _counts_active_development_time(running_row):
            development_seconds += _run_duration_seconds(running_row, now=now)

    def _count_mode(mode: str) -> int:
        return sum(
            1
            for r in finished
            if r.mode == mode and r.outcome not in _EXCLUDED_OUTCOMES
        )

    build_runs = _count_mode("build")
    feedback_runs = _count_mode("feedback")
    post_production_runs = _count_mode("post_production")
    sp = get_self_propelling_settings(project_id, ws)
    improvement_cycles = int(sp.get("cycles_completed") or 0)
    if improvement_cycles < post_production_runs:
        improvement_cycles = post_production_runs

    completed_runs = sum(1 for r in finished if r.outcome == "completed")
    blocked_runs = sum(1 for r in finished if r.outcome == "blocked")
    stopped_runs = sum(1 for r in finished if r.outcome == "stopped")

    durations = [_run_duration_seconds(r) for r in active_runs]
    post_prod_durations = [
        _run_duration_seconds(r)
        for r in active_runs
        if r.mode == "post_production"
    ]

    tasks_completed = (
        await session.scalar(
            select(func.count(TaskRow.id)).where(
                TaskRow.project_id == project_id,
                TaskRow.status == "completed",
            )
        )
        or 0
    )
    deployments = (
        await session.scalar(
            select(func.count(DeploymentRow.id)).where(DeploymentRow.project_id == project_id)
        )
        or 0
    )

    first_at = runs[0].started_at if runs else None
    last_finished = max((r.finished_at for r in finished if r.finished_at), default=None)
    last_at = last_finished or (runs[-1].started_at if runs else None)

    countable_finished = len(active_runs)
    success_rate = (
        round(completed_runs / countable_finished, 3) if countable_finished else None
    )

    waiting_for_production = project_state == ProjectState.REVIEW.value

    return {
        "development_seconds": int(round(development_seconds)),
        "development_active": development_active,
        "pipeline_runs_total": len(finished),
        "pipeline_runs_completed": completed_runs,
        "pipeline_runs_blocked": blocked_runs,
        "pipeline_runs_stopped": stopped_runs,
        "build_cycles": build_runs,
        "feedback_iterations": feedback_runs,
        "improvement_cycles": improvement_cycles,
        "post_production_runs": post_production_runs,
        "total_cycles": build_runs + feedback_runs + improvement_cycles,
        "mean_cycle_seconds": _avg(durations),
        "mean_improvement_cycle_seconds": _avg(post_prod_durations),
        "total_fix_attempts": sum(int(r.fix_attempts or 0) for r in finished),
        "total_human_interventions": sum(int(r.human_interventions or 0) for r in finished),
        "tasks_completed": int(tasks_completed),
        "deployments": int(deployments),
        "success_rate": success_rate,
        "waiting_for_production": waiting_for_production,
        "first_activity_at": first_at.isoformat() if first_at else None,
        "last_activity_at": last_at.isoformat() if last_at else None,
    }


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)
