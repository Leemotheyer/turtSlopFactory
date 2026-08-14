"""Persisted factory-wide settings (agent backend, deployment, API key)."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import FactorySettingsRow
from app.services.crypto import encrypt_value
from app.services.cursor_connection import get_connection_row
from app.services.deployment_urls import (
    build_public_origin,
    maybe_auto_configure,
    resolve_request_context,
)

VALID_AGENT_BACKENDS = frozenset({"cursor_cloud", "cursor_local", "local"})
CURSOR_MODEL_ROLES = ("architect", "developer", "reviewer")


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


async def get_preview_origin(session: AsyncSession, request: Request | None = None) -> str:
    """Public factory origin for live preview links (includes gateway port when needed)."""
    row = await get_or_create_settings_row(session)
    stored = row.preview_host or settings.public_host or settings.preview_host

    if request is not None and settings.trust_proxy_headers:
        _, api_url, _, gateway = resolve_request_context(request)
        if gateway:
            return api_url.rstrip("/")

    return build_public_origin(stored, public_port=settings.dashboard_port)


async def get_agent_backend(session: AsyncSession) -> str:
    row = await get_or_create_settings_row(session)
    backend = row.agent_backend
    if backend not in VALID_AGENT_BACKENDS:
        return settings.agent_backend
    return backend


async def get_agent_model(session: AsyncSession) -> str:
    models = await get_agent_models(session)
    return models["developer"]


async def get_agent_models(session: AsyncSession) -> dict[str, str]:
    row = await get_or_create_settings_row(session)
    base = row.agent_model or settings.cursor_agent_model
    stored = row.agent_models if isinstance(row.agent_models, dict) else {}
    return {
        role: (stored.get(role) or base).strip() or settings.cursor_agent_model
        for role in CURSOR_MODEL_ROLES
    }


async def get_agent_model_for_role(session: AsyncSession, role: str) -> str:
    models = await get_agent_models(session)
    return models.get(role, settings.cursor_agent_model)


async def get_max_parallel_agents(session: AsyncSession) -> int:
    row = await get_or_create_settings_row(session)
    if row.max_parallel_agents is not None and row.max_parallel_agents > 0:
        return row.max_parallel_agents
    return settings.max_parallel_agents


async def get_cursor_concurrent_limit(session: AsyncSession) -> int:
    row = await get_or_create_settings_row(session)
    if row.cursor_concurrent_limit is not None and row.cursor_concurrent_limit > 0:
        return row.cursor_concurrent_limit
    return settings.cursor_concurrent_agent_limit


async def set_agent_backend(session: AsyncSession, backend: str) -> dict:
    if backend not in VALID_AGENT_BACKENDS:
        raise ValueError(f"agent_backend must be one of: {', '.join(sorted(VALID_AGENT_BACKENDS))}")
    row = await get_or_create_settings_row(session)
    row.agent_backend = backend
    await session.commit()
    return await get_factory_settings(session)


async def set_agent_model(session: AsyncSession, model: str) -> dict:
    model_id = model.strip()
    if not model_id:
        raise ValueError("agent_model is required")
    row = await get_or_create_settings_row(session)
    row.agent_model = model_id
    row.agent_models = {role: model_id for role in CURSOR_MODEL_ROLES}
    await session.commit()
    return await get_factory_settings(session)


async def set_agent_models(session: AsyncSession, updates: dict[str, str | None]) -> dict:
    row = await get_or_create_settings_row(session)
    current = dict(row.agent_models) if isinstance(row.agent_models, dict) else {}
    for role, model_id in updates.items():
        if role not in CURSOR_MODEL_ROLES:
            raise ValueError(f"Unknown role: {role}")
        if model_id is None or not str(model_id).strip():
            current.pop(role, None)
            continue
        cleaned = str(model_id).strip()
        if not cleaned:
            raise ValueError(f"agent model for {role} cannot be blank")
        current[role] = cleaned
    row.agent_models = current or None
    await session.commit()
    return await get_factory_settings(session)


async def set_preview_host(session: AsyncSession, preview_host: str, request: Request | None = None) -> dict:
    host = preview_host.strip()
    if not host:
        raise ValueError("preview_host is required")
    row = await get_or_create_settings_row(session)
    row.preview_host = host
    row.setup_complete = True
    await session.commit()
    return await get_setup_status(session, request)


async def set_instance_api_key(session: AsyncSession, api_key: str | None, request: Request | None = None) -> dict:
    row = await get_or_create_settings_row(session)
    if api_key:
        row.encrypted_api_key = encrypt_value(api_key.strip())
    else:
        row.encrypted_api_key = None
    await session.commit()
    return await get_setup_status(session, request)


async def complete_setup(
    session: AsyncSession, *, preview_host: str | None = None, request: Request | None = None
) -> dict:
    row = await get_or_create_settings_row(session)
    if preview_host:
        row.preview_host = preview_host.strip()
    row.setup_complete = True
    await session.commit()
    return await get_setup_status(session, request)


async def get_setup_status(session: AsyncSession, request: Request | None = None) -> dict:
    row = await get_or_create_settings_row(session)
    row = await maybe_auto_configure(session, row, request)
    try:
        cursor = await get_connection_row(session)
    except Exception:
        cursor = None

    detected_host, api_url, ws_url, gateway_mode = resolve_request_context(request)
    host = row.preview_host or settings.public_host or detected_host or settings.preview_host
    if not gateway_mode:
        api_url = f"http://{host}:{settings.api_port}"
        ws_url = f"ws://{host}:{settings.api_port}"

    from app.services.instance_auth import api_key_required
    from app.services.github_connection import get_github_connection_status

    github = await get_github_connection_status(session)

    return {
        "setup_complete": row.setup_complete,
        "preview_host": host,
        "api_url": api_url,
        "ws_url": ws_url,
        "gateway_mode": gateway_mode,
        "api_port": settings.api_port,
        "dashboard_port": settings.dashboard_port,
        "api_key_required": api_key_required(),
        "api_key_configured": bool(settings.api_key or row.encrypted_api_key),
        "cursor_connected": cursor is not None,
        "github_token_configured": github.get("connected", False),
        "github_login": github.get("github_login"),
        "masked_github_token": github.get("masked_github_token"),
        "github_token_source": github.get("source"),
        "agent_backend": await get_agent_backend(session),
        "valid_backends": sorted(VALID_AGENT_BACKENDS),
        "agent_model": (await get_agent_models(session))["developer"],
        "agent_models": await get_agent_models(session),
        "max_parallel_agents": await get_max_parallel_agents(session),
        "cursor_concurrent_limit": await get_cursor_concurrent_limit(session),
        "auto_configured": {
            "encryption_key": not bool(settings.secrets_encryption_key),
            "database": True,
            "gateway": gateway_mode,
        },
    }


async def get_factory_settings(session: AsyncSession, request: Request | None = None) -> dict:
    status = await get_setup_status(session, request)
    return {
        "agent_backend": status["agent_backend"],
        "default_agent_backend": settings.agent_backend,
        "valid_backends": status["valid_backends"],
        "agent_model": (await get_agent_models(session))["developer"],
        "agent_models": await get_agent_models(session),
        "default_agent_model": settings.cursor_agent_model,
        "max_parallel_agents": await get_max_parallel_agents(session),
        "default_max_parallel_agents": settings.max_parallel_agents,
        "cursor_concurrent_limit": await get_cursor_concurrent_limit(session),
        "default_cursor_concurrent_limit": settings.cursor_concurrent_agent_limit,
        "cursor_model": (await get_agent_models(session))["developer"],
        "preview_host": status["preview_host"],
        "setup_complete": status["setup_complete"],
    }


async def get_public_config(session: AsyncSession, request: Request | None = None) -> dict:
    """Config the dashboard fetches at runtime (no secrets)."""
    status = await get_setup_status(session, request)
    return {
        "api_url": status["api_url"],
        "ws_url": status["ws_url"],
        "preview_host": status["preview_host"],
        "setup_complete": status["setup_complete"],
        "api_key_required": status["api_key_required"],
        "gateway_mode": status["gateway_mode"],
    }
