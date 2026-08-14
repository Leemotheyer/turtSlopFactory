from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.agent_concurrency import concurrency_budget_to_dict, resolve_concurrency_budget
from app.services.cursor_client import CursorApiError
from app.services.cursor_connection import (
    connect_cursor,
    disconnect_cursor,
    fetch_usage,
    get_connection_status,
    list_cursor_agents,
    list_cursor_models,
    list_github_repositories,
)
from app.services.factory_settings import get_factory_settings

router = APIRouter(prefix="/cursor", tags=["cursor"])


class CursorConnectRequest(BaseModel):
    api_key: str


@router.get("/status")
async def cursor_status(db: AsyncSession = Depends(get_db)) -> dict:
    status = await get_connection_status(db)
    factory = await get_factory_settings(db)
    budget = await resolve_concurrency_budget(db)
    return {**status, **factory, "concurrency": concurrency_budget_to_dict(budget)}


@router.post("/connect")
async def cursor_connect(body: CursorConnectRequest, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await connect_cursor(db, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CursorApiError as exc:
        if exc.status in (401, 403):
            raise HTTPException(
                status_code=exc.status,
                detail=f"Cursor rejected this API key: {exc.message}",
            ) from exc
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.delete("/disconnect")
async def cursor_disconnect(db: AsyncSession = Depends(get_db)) -> dict:
    return await disconnect_cursor(db)


@router.get("/usage")
async def cursor_usage(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await fetch_usage(db)
    except CursorApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/agents")
async def cursor_agents(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await list_cursor_agents(db)
    except CursorApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/repositories")
async def cursor_repositories(
    refresh: bool = False, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await list_github_repositories(db, refresh=refresh)
    except CursorApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.get("/models")
async def cursor_models(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await list_cursor_models(db)
    except CursorApiError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
