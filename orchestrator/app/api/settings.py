from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.pipeline.executor import pipeline_executor
from app.services.factory_settings import (
    complete_setup,
    get_factory_settings,
    get_public_config,
    get_setup_status,
    set_agent_backend,
    set_instance_api_key,
    set_preview_host,
)
from app.services.instance_auth import refresh_api_key_cache

router = APIRouter(prefix="/settings", tags=["settings"])


class AgentBackendRequest(BaseModel):
    agent_backend: str


class PreviewHostRequest(BaseModel):
    preview_host: str


class ApiKeyRequest(BaseModel):
    api_key: str | None = None


class SetupRequest(BaseModel):
    preview_host: str | None = None
    api_key: str | None = None


@router.get("/public")
async def public_config(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_public_config(db)


@router.get("/setup")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_setup_status(db)


@router.post("/setup")
async def finish_setup(body: SetupRequest, db: AsyncSession = Depends(get_db)) -> dict:
    if body.preview_host:
        await set_preview_host(db, body.preview_host)
    if body.api_key is not None:
        await set_instance_api_key(db, body.api_key or None)
        await refresh_api_key_cache(db)
    return await complete_setup(db, preview_host=body.preview_host)


@router.get("/factory")
async def factory_settings(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_factory_settings(db)


@router.put("/factory/agent-backend")
async def update_agent_backend(
    body: AgentBackendRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        result = await set_agent_backend(db, body.agent_backend)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pipeline_executor.runner.invalidate_settings_cache()
    return result


@router.put("/factory/preview-host")
async def update_preview_host(
    body: PreviewHostRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await set_preview_host(db, body.preview_host)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/factory/api-key")
async def update_api_key(body: ApiKeyRequest, db: AsyncSession = Depends(get_db)) -> dict:
    result = await set_instance_api_key(db, body.api_key)
    await refresh_api_key_cache(db)
    return result
