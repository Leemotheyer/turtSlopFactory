"""Runtime API key resolution (env or dashboard-configured)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.crypto import decrypt_value
from app.services.factory_settings import get_or_create_settings_row

logger = logging.getLogger(__name__)

_cached_api_key: str | None = None


async def refresh_api_key_cache(session: AsyncSession) -> None:
    global _cached_api_key
    if settings.api_key:
        _cached_api_key = settings.api_key
        return
    row = await get_or_create_settings_row(session)
    if row.encrypted_api_key:
        try:
            _cached_api_key = decrypt_value(row.encrypted_api_key)
        except Exception:
            logger.exception("Failed to decrypt stored API key")
            _cached_api_key = None
    else:
        _cached_api_key = None


def get_effective_api_key() -> str | None:
    if settings.api_key:
        return settings.api_key
    return _cached_api_key


def api_key_required() -> bool:
    return bool(get_effective_api_key())
