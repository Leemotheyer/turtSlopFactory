import logging
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import NotificationRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, Notification, NotificationType

logger = logging.getLogger(__name__)


def _to_model(row: NotificationRow) -> Notification:
    return Notification(
        id=row.id,
        project_id=row.project_id,
        type=NotificationType(row.type),
        title=row.title,
        message=row.message,
        action=row.action,
        reference_id=row.reference_id,
        read=row.read,
        created_at=row.created_at,
    )


async def create_notification(
    session: AsyncSession,
    project_id: UUID | None,
    type: NotificationType,
    title: str,
    message: str,
    action: str | None = None,
    reference_id: UUID | None = None,
) -> Notification:
    row = NotificationRow(
        project_id=project_id,
        type=type.value,
        title=title,
        message=message,
        action=action,
        reference_id=reference_id,
        read=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    notification = _to_model(row)
    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.NOTIFICATION_CREATED,
            project_id=project_id,
            payload={
                "notification_id": str(row.id),
                "type": type.value,
                "title": title,
                "message": message,
                "action": action,
            },
        ),
    )
    return notification


async def list_notifications(
    session: AsyncSession,
    unread_only: bool = False,
    limit: int = 50,
) -> list[Notification]:
    query = select(NotificationRow).order_by(NotificationRow.created_at.desc()).limit(limit)
    if unread_only:
        query = query.where(NotificationRow.read.is_(False))
    result = await session.execute(query)
    return [_to_model(r) for r in result.scalars()]


async def count_unread(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(NotificationRow).where(NotificationRow.read.is_(False))
    )
    return result.scalar() or 0


async def mark_read(session: AsyncSession, notification_id: UUID) -> bool:
    row = await session.get(NotificationRow, notification_id)
    if not row:
        return False
    row.read = True
    await session.commit()
    return True


async def mark_all_read(session: AsyncSession) -> int:
    result = await session.execute(
        update(NotificationRow).where(NotificationRow.read.is_(False)).values(read=True)
    )
    await session.commit()
    return result.rowcount
