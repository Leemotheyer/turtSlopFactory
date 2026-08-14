from fastapi import APIRouter, Depends, HTTPException, Request
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
    set_agent_model,
    set_agent_models,
    set_instance_api_key,
    set_preview_host,
)
from app.services.instance_auth import refresh_api_key_cache

router = APIRouter(prefix="/settings", tags=["settings"])


class AgentBackendRequest(BaseModel):
    agent_backend: str


class AgentModelRequest(BaseModel):
    agent_model: str


class AgentModelsRequest(BaseModel):
    architect: str | None = None
    developer: str | None = None
    reviewer: str | None = None


class PreviewHostRequest(BaseModel):
    preview_host: str


class ApiKeyRequest(BaseModel):
    api_key: str | None = None


class SetupRequest(BaseModel):
    preview_host: str | None = None
    api_key: str | None = None


@router.get("/public")
async def public_config(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_public_config(db, request)


@router.get("/setup")
async def setup_status(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_setup_status(db, request)


@router.post("/setup")
async def finish_setup(
    body: SetupRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    if body.preview_host:
        await set_preview_host(db, body.preview_host, request)
    if body.api_key is not None:
        await set_instance_api_key(db, body.api_key or None, request)
        await refresh_api_key_cache(db)
    return await complete_setup(db, preview_host=body.preview_host, request=request)


@router.get("/factory")
async def factory_settings(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_factory_settings(db, request)


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


@router.put("/factory/agent-model")
async def update_agent_model(body: AgentModelRequest, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        result = await set_agent_model(db, body.agent_model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pipeline_executor.runner.invalidate_settings_cache()
    return result


@router.put("/factory/agent-models")
async def update_agent_models(body: AgentModelsRequest, db: AsyncSession = Depends(get_db)) -> dict:
    updates = {
        role: value
        for role, value in body.model_dump().items()
        if value is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one role model to update")
    try:
        result = await set_agent_models(db, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pipeline_executor.runner.invalidate_settings_cache()
    return result


@router.put("/factory/preview-host")
async def update_preview_host(
    body: PreviewHostRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await set_preview_host(db, body.preview_host, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/factory/api-key")
async def update_api_key(
    body: ApiKeyRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await set_instance_api_key(db, body.api_key, request)
    await refresh_api_key_cache(db)
    if body.api_key:
        result["verified"] = True
        result["message"] = "Factory API key saved. Use the same value in this browser to access the API."
    else:
        result["verified"] = True
        result["message"] = "Factory API key removed. API access is no longer protected."
    return result


@router.get("/verify-key")
async def verify_api_key() -> dict:
    """Confirm the caller's X-API-Key is accepted (requires a configured factory key)."""
    return {"verified": True, "message": "Factory API key is valid."}
