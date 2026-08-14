"""Persist and verify factory-wide GitHub credentials."""

from __future__ import annotations

import logging
import os

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.crypto import decrypt_value, encrypt_value, mask_value
from app.services.factory_settings import get_or_create_settings_row

logger = logging.getLogger(__name__)


class GitHubTokenError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        self.message = message
        self.status = status
        super().__init__(message)


async def verify_github_token(token: str) -> dict[str, str | None]:
    token = token.strip()
    if not token:
        raise GitHubTokenError("GitHub token is required", status=400)

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    if response.status_code in (401, 403):
        raise GitHubTokenError("GitHub rejected this token — check it has repo scope", status=response.status_code)
    if response.status_code >= 400:
        raise GitHubTokenError(f"GitHub API error ({response.status_code})", status=response.status_code)

    data = response.json()
    return {
        "login": data.get("login"),
        "name": data.get("name"),
    }


async def get_github_connection_status(session: AsyncSession) -> dict:
    row = await get_or_create_settings_row(session)
    if row.encrypted_github_token:
        try:
            plain = decrypt_value(row.encrypted_github_token)
        except Exception:
            logger.exception("Failed to decrypt stored GitHub token")
            plain = None
        if plain:
            return {
                "connected": True,
                "github_login": row.github_login,
                "masked_github_token": mask_value(plain),
            }

    if os.environ.get("GITHUB_TOKEN") or settings.github_token:
        return {
            "connected": True,
            "github_login": None,
            "masked_github_token": "env",
            "source": "environment",
        }

    return {"connected": False}


async def connect_github_token(session: AsyncSession, token: str) -> dict:
    profile = await verify_github_token(token)
    row = await get_or_create_settings_row(session)
    row.encrypted_github_token = encrypt_value(token.strip())
    row.github_login = profile.get("login")
    await session.commit()
    await session.refresh(row)

    login = profile.get("login") or "GitHub user"
    return {
        "connected": True,
        "verified": True,
        "github_login": profile.get("login"),
        "masked_github_token": mask_value(token.strip()),
        "message": f"GitHub token verified and saved for {login}. Factory branches will push automatically.",
    }


async def disconnect_github_token(session: AsyncSession) -> dict:
    row = await get_or_create_settings_row(session)
    row.encrypted_github_token = None
    row.github_login = None
    await session.commit()
    return {"connected": False, "message": "GitHub token removed from factory settings."}


async def resolve_github_token(session: AsyncSession) -> str | None:
    """Factory-stored token, then env fallback."""
    row = await get_or_create_settings_row(session)
    if row.encrypted_github_token:
        try:
            return decrypt_value(row.encrypted_github_token)
        except Exception:
            logger.exception("Failed to decrypt factory GitHub token")
    return os.environ.get("GITHUB_TOKEN") or settings.github_token
