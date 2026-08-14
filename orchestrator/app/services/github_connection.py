"""Persist and verify factory-wide GitHub credentials."""

from __future__ import annotations

import logging
import os

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.crypto import decrypt_value, encrypt_value, mask_value
from app.services.factory_settings import get_or_create_settings_row
from app.workspace.provisioner import repo_display_name

logger = logging.getLogger(__name__)

_GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubTokenError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        self.message = message
        self.status = status
        super().__init__(message)


def _parse_repo_owner_name(repo_url: str) -> tuple[str, str]:
    slug = repo_display_name(repo_url)
    if "/" not in slug:
        raise ValueError(f"Invalid GitHub repository URL: {repo_url}")
    owner, name = slug.split("/", 1)
    return owner, name


def _classic_token_has_push_scope(scopes_header: str) -> bool:
    scopes = {part.strip().lower() for part in scopes_header.split(",") if part.strip()}
    if not scopes:
        return True  # fine-grained tokens omit X-OAuth-Scopes
    return "repo" in scopes or "public_repo" in scopes


def _explain_push_denial(stderr: str, repo_url: str | None = None) -> str:
    repo_hint = ""
    if repo_url:
        try:
            repo_hint = f" on {repo_display_name(repo_url)}"
        except ValueError:
            pass

    if "403" in stderr or "denied" in stderr.lower():
        return (
            f"GitHub rejected the push{repo_hint}. Your token can sign in but does not have write access. "
            "Create a classic personal access token with the repo scope, or a fine-grained token with "
            "Contents: Read and write for this repository, then reconnect GitHub in the Cursor menu."
        )
    if "401" in stderr or "authentication failed" in stderr.lower():
        return "GitHub authentication failed. Reconnect your GitHub token in the Cursor menu."
    return stderr.strip()[:400] or "Git push failed"


async def verify_repo_push_access(token: str, repo_url: str) -> dict[str, object]:
    owner, name = _parse_repo_owner_name(repo_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"https://api.github.com/repos/{owner}/{name}",
            headers={**_GITHUB_API_HEADERS, "Authorization": f"Bearer {token}"},
        )

    if response.status_code == 404:
        return {
            "can_push": False,
            "message": (
                f"Token cannot access {owner}/{name}. "
                "If this is a fine-grained PAT, grant it access to that repository."
            ),
        }
    if response.status_code in (401, 403):
        return {
            "can_push": False,
            "message": (
                f"Token cannot access {owner}/{name}. "
                "Check the PAT scopes or fine-grained repository permissions."
            ),
        }
    if response.status_code >= 400:
        return {"can_push": False, "message": f"GitHub API error ({response.status_code}) checking repo access."}

    permissions = response.json().get("permissions") or {}
    if permissions.get("push") or permissions.get("admin"):
        return {"can_push": True, "repo": f"{owner}/{name}"}

    return {
        "can_push": False,
        "message": (
            f"GitHub token is read-only for {owner}/{name}. "
            "Use a classic PAT with repo scope, or a fine-grained PAT with Contents: Read and write."
        ),
    }


async def verify_github_token(token: str, *, repo_url: str | None = None) -> dict[str, str | None]:
    token = token.strip()
    if not token:
        raise GitHubTokenError("GitHub token is required", status=400)

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={**_GITHUB_API_HEADERS, "Authorization": f"Bearer {token}"},
        )

    if response.status_code in (401, 403):
        raise GitHubTokenError("GitHub rejected this token", status=response.status_code)
    if response.status_code >= 400:
        raise GitHubTokenError(f"GitHub API error ({response.status_code})", status=response.status_code)

    scopes_header = response.headers.get("X-OAuth-Scopes", "")
    if scopes_header and not _classic_token_has_push_scope(scopes_header):
        raise GitHubTokenError(
            "This token is missing the repo scope required to push branches. "
            "Create a classic PAT at https://github.com/settings/tokens and enable the repo checkbox.",
            status=403,
        )

    data = response.json()
    profile = {
        "login": data.get("login"),
        "name": data.get("name"),
    }

    if repo_url:
        push = await verify_repo_push_access(token, repo_url)
        if not push.get("can_push"):
            raise GitHubTokenError(str(push.get("message")), status=403)

    return profile


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
