from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.github_connection import (
    GitHubTokenError,
    connect_github_token,
    disconnect_github_token,
    get_github_connection_status,
)

router = APIRouter(prefix="/github", tags=["github"])


class GitHubConnectRequest(BaseModel):
    token: str


@router.get("/status")
async def github_status(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_github_connection_status(db)


@router.post("/connect")
async def github_connect(body: GitHubConnectRequest, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await connect_github_token(db, body.token)
    except GitHubTokenError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.delete("/disconnect")
async def github_disconnect(db: AsyncSession = Depends(get_db)) -> dict:
    return await disconnect_github_token(db)
