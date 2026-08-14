"""Persisted factory-wide settings (agent backend, deployment, API key)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import FactorySettingsRow
from app.services.crypto import encrypt_value
from app.services.cursor_connection import get_connection_row

VALID_AGENT_BACKENDS = frozenset({"cursor_cloud", "cursor_local", "local"})


async def get_or_create_settings_row(session: AsyncSession) -> FactorySettingsRow:
    result = await session.execute(select(FactorySettingsRow).where(FactorySettingsRow.id == 1))
    row = result.scalar_one_or_none()
    if row:
        return row
    row = FactorySettingsRow(
        id=1,
        agent_backend=settings.agent_backend,
        preview_host=settings.public_host or settings.preview_host,
        setup_complete=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_preview_host(session: AsyncSession) -> str:
    row = await get_or_create_settings_row(session)
    return row.preview_host or settings.public_host or settings.preview_host


async def get_agent_backend(session: AsyncSession) -> str:
    row = await get_or_create_settings_row(session)
    backend = row.agent_backend
    if backend not in VALID_AGENT_BACKENDS:
        return settings.agent_backend
    return backend


async def set_agent_backend(session: AsyncSession, backend: str) -> dict:
    if backend not in VALID_AGENT_BACKENDS:
        raise ValueError(f"agent_backend must be one of: {', '.join(sorted(VALID_AGENT_BACKENDS))}")
    row = await get_or_create_settings_row(session)
    row.agent_backend = backend
    await session.commit()
    return await get_factory_settings(session)


async def set_preview_host(session: AsyncSession, preview_host: str) -> dict:
    host = preview_host.strip()
    if not host:
        raise ValueError("preview_host is required")
    row = await get_or_create_settings_row(session)
    row.preview_host = host
    row.setup_complete = True
    await session.commit()
    return await get_setup_status(session)


async def set_instance_api_key(session: AsyncSession, api_key: str | None) -> dict:
    row = await get_or_create_settings_row(session)
    if api_key:
        row.encrypted_api_key = encrypt_value(api_key.strip())
    else:
        row.encrypted_api_key = None
    await session.commit()
    return await get_setup_status(session)


async def complete_setup(session: AsyncSession, *, preview_host: str | None = None) -> dict:
    row = await get_or_create_settings_row(session)
    if preview_host:
        row.preview_host = preview_host.strip()
    row.setup_complete = True
    await session.commit()
    return await get_setup_status(session)


async def get_setup_status(session: AsyncSession) -> dict:
    row = await get_or_create_settings_row(session)
    try:
        cursor = await get_connection_row(session)
    except Exception:
        cursor = None
    host = row.preview_host or settings.public_host or settings.preview_host
    api_url = f"http://{host}:{settings.api_port}"
    ws_url = f"ws://{host}:{settings.api_port}"
    from app.services.instance_auth import api_key_required

    return {
        "setup_complete": row.setup_complete,
        "preview_host": host,
        "api_url": api_url,
        "ws_url": ws_url,
        "api_port": settings.api_port,
        "dashboard_port": settings.dashboard_port,
        "api_key_required": api_key_required(),
        "api_key_configured": bool(settings.api_key or row.encrypted_api_key),
        "cursor_connected": cursor is not None,
        "agent_backend": await get_agent_backend(session),
        "valid_backends": sorted(VALID_AGENT_BACKENDS),
        "auto_configured": {
            "encryption_key": not bool(settings.secrets_encryption_key),
            "database": True,
        },
    }


async def get_factory_settings(session: AsyncSession) -> dict:
    status = await get_setup_status(session)
    return {
        "agent_backend": status["agent_backend"],
        "default_agent_backend": settings.agent_backend,
        "valid_backends": status["valid_backends"],
        "cursor_model": settings.cursor_agent_model,
        "preview_host": status["preview_host"],
        "setup_complete": status["setup_complete"],
    }


async def get_public_config(session: AsyncSession) -> dict:
    """Config the dashboard fetches at runtime (no secrets)."""
    status = await get_setup_status(session)
    return {
        "api_url": status["api_url"],
        "ws_url": status["ws_url"],
        "preview_host": status["preview_host"],
        "setup_complete": status["setup_complete"],
        "api_key_required": status["api_key_required"],
    }
