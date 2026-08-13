from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Notification
from app.services.notifications import count_unread, list_notifications, mark_all_read, mark_read

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[Notification])
async def get_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    return await list_notifications(db, unread_only=unread_only, limit=limit)


@router.get("/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db)) -> dict:
    return {"count": await count_unread(db)}


@router.post("/{notification_id}/read")
async def read_notification(notification_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    if not await mark_read(db, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "read"}


@router.post("/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db)) -> dict:
    count = await mark_all_read(db)
    return {"status": "ok", "marked_read": count}
