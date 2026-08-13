"""Persisted factory-wide settings (agent backend, etc.)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import FactorySettingsRow

VALID_AGENT_BACKENDS = frozenset({"cursor_cloud", "cursor_local", "local"})


async def _get_or_create_row(session: AsyncSession) -> FactorySettingsRow:
    result = await session.execute(select(FactorySettingsRow).where(FactorySettingsRow.id == 1))
    row = result.scalar_one_or_none()
    if row:
        return row
    row = FactorySettingsRow(id=1, agent_backend=settings.agent_backend)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_agent_backend(session: AsyncSession) -> str:
    row = await _get_or_create_row(session)
    backend = row.agent_backend
    if backend not in VALID_AGENT_BACKENDS:
        return settings.agent_backend
    return backend


async def set_agent_backend(session: AsyncSession, backend: str) -> dict:
    if backend not in VALID_AGENT_BACKENDS:
        raise ValueError(f"agent_backend must be one of: {', '.join(sorted(VALID_AGENT_BACKENDS))}")
    row = await _get_or_create_row(session)
    row.agent_backend = backend
    await session.commit()
    return await get_factory_settings(session)


async def get_factory_settings(session: AsyncSession) -> dict:
    backend = await get_agent_backend(session)
    return {
        "agent_backend": backend,
        "default_agent_backend": settings.agent_backend,
        "valid_backends": sorted(VALID_AGENT_BACKENDS),
        "cursor_model": settings.cursor_agent_model,
    }
