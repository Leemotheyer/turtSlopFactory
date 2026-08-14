"""First-run bootstrap: auto-generate encryption keys and ensure schema."""

from __future__ import annotations

import logging
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal, engine
from app.services.instance_auth import refresh_api_key_cache

logger = logging.getLogger(__name__)

_KEY_FILE = Path(settings.workspace_root) / ".factory" / "encryption.key"
_ephemeral_key: str | None = None


def ensure_encryption_key() -> str:
    """Return a Fernet key from env, persisted file, or a newly generated file."""
    global _ephemeral_key
    if settings.secrets_encryption_key:
        return settings.secrets_encryption_key

    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            return _KEY_FILE.read_text().strip()

        key = Fernet.generate_key().decode()
        _KEY_FILE.write_text(key)
        _KEY_FILE.chmod(0o600)
        logger.info("Generated instance encryption key at %s", _KEY_FILE)
        return key
    except OSError as exc:
        if _ephemeral_key is None:
            _ephemeral_key = Fernet.generate_key().decode()
            logger.warning("Could not persist encryption key (%s); using in-memory key", exc)
        return _ephemeral_key


async def _ensure_factory_settings_columns() -> None:
    """Add new factory_settings columns on existing databases (no Alembic)."""
    statements = [
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS preview_host VARCHAR(255)",
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS encrypted_api_key TEXT",
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS setup_complete BOOLEAN DEFAULT FALSE",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def run_instance_bootstrap() -> None:
    ensure_encryption_key()
    await _ensure_factory_settings_columns()
    async with SessionLocal() as session:
        from app.services.factory_settings import get_or_create_settings_row

        await get_or_create_settings_row(session)
        await refresh_api_key_cache(session)
