import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import InputRequestRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, InputRequest, InputRequestStatus

logger = logging.getLogger(__name__)


def _to_model(row: InputRequestRow) -> InputRequest:
    return InputRequest(
        id=row.id,
        project_id=row.project_id,
        task_id=row.task_id,
        agent_id=row.agent_id,
        role=row.role,
        question=row.question,
        context_detail=row.context_detail,
        options=row.options or [],
        default_decision=row.default_decision,
        status=InputRequestStatus(row.status),
        human_response=row.human_response,
        resolved_decision=row.resolved_decision,
        expires_at=row.expires_at,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


async def create_input_request(
    session: AsyncSession,
    project_id: UUID,
    agent_id: str,
    role: str,
    question: str,
    default_decision: str,
    context_detail: str = "",
    options: list[str] | None = None,
    task_id: UUID | None = None,
) -> InputRequest:
    """
    Create a non-blocking input request. The agent proceeds immediately with default_decision.
    Human can optionally respond before expiry; otherwise it auto-resolves.
    """
    expires_at = datetime.utcnow() + timedelta(seconds=settings.input_request_timeout_seconds)

    row = InputRequestRow(
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        role=role,
        question=question,
        context_detail=context_detail,
        options=options or [],
        default_decision=default_decision,
        status=InputRequestStatus.OPEN.value,
        resolved_decision=default_decision,
        expires_at=expires_at,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.INPUT_REQUESTED,
            project_id=project_id,
            task_id=task_id,
            agent_id=agent_id,
            payload={
                "question": question,
                "default_decision": default_decision,
                "expires_at": expires_at.isoformat(),
                "non_blocking": True,
            },
        ),
    )

    return _to_model(row)


async def respond_to_input(
    session: AsyncSession,
    project_id: UUID,
    request_id: UUID,
    response: str,
) -> InputRequest | None:
    row = await session.get(InputRequestRow, request_id)
    if not row or row.project_id != project_id:
        return None
    if row.status != InputRequestStatus.OPEN.value:
        return None

    row.human_response = response
    row.resolved_decision = response
    row.status = InputRequestStatus.ANSWERED.value
    row.resolved_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.INPUT_RESOLVED,
            project_id=project_id,
            agent_id=row.agent_id,
            payload={
                "request_id": str(request_id),
                "status": "answered",
                "decision": response,
            },
        ),
    )

    return _to_model(row)


async def expire_stale_requests(session: AsyncSession) -> int:
    """Auto-resolve open requests past their expiry. Pipeline never waits."""
    now = datetime.utcnow()
    result = await session.execute(
        select(InputRequestRow).where(
            InputRequestRow.status == InputRequestStatus.OPEN.value,
            InputRequestRow.expires_at <= now,
        )
    )
    rows = result.scalars().all()
    count = 0

    for row in rows:
        row.status = InputRequestStatus.AUTO_RESOLVED.value
        row.resolved_decision = row.default_decision
        row.resolved_at = now
        count += 1

        await event_bus.publish(
            session,
            FactoryEvent(
                type=EventType.INPUT_RESOLVED,
                project_id=row.project_id,
                agent_id=row.agent_id,
                payload={
                    "request_id": str(row.id),
                    "status": "auto_resolved",
                    "decision": row.default_decision,
                },
            ),
        )

    if count:
        await session.commit()
        logger.info("Auto-resolved %d input requests", count)

    return count


async def list_input_requests(
    session: AsyncSession,
    project_id: UUID,
    status: str | None = None,
) -> list[InputRequest]:
    query = (
        select(InputRequestRow)
        .where(InputRequestRow.project_id == project_id)
        .order_by(InputRequestRow.created_at.desc())
    )
    if status:
        query = query.where(InputRequestRow.status == status)

    result = await session.execute(query)
    return [_to_model(r) for r in result.scalars()]
