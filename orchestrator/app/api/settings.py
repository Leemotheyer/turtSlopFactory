from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.pipeline.executor import pipeline_executor
from app.services.factory_settings import get_factory_settings, set_agent_backend

router = APIRouter(prefix="/settings", tags=["settings"])


class AgentBackendRequest(BaseModel):
    agent_backend: str


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
