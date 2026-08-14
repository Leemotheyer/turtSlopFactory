"""First-run bootstrap: auto-generate encryption keys and ensure schema."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal, engine
from app.services.instance_auth import refresh_api_key_cache

logger = logging.getLogger(__name__)

_ephemeral_key: str | None = None


def _config_dir() -> Path:
    return Path(settings.factory_config_dir)


def _key_paths() -> list[Path]:
    """Preferred config dir, with legacy paths for upgrades."""
    return [
        _config_dir() / "encryption.key",
        Path("/data/factory") / "encryption.key",
        Path(settings.workspace_root) / ".factory" / "encryption.key",
    ]


def load_local_env_overrides() -> None:
    """Apply ./data/config/local.env without overriding existing process env."""
    env_file = _config_dir() / "local.env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    logger.info("Loaded config overrides from %s", env_file)


def ensure_encryption_key() -> str:
    """Return a Fernet key from env, persisted file, or a newly generated file."""
    global _ephemeral_key
    if settings.secrets_encryption_key:
        return settings.secrets_encryption_key

    for path in _key_paths():
        if path.exists():
            return path.read_text().strip()

    target = _key_paths()[0]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key().decode()
        target.write_text(key)
        target.chmod(0o600)
        logger.info("Generated instance encryption key at %s", target)
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
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS agent_model VARCHAR(128)",
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS agent_models JSONB",
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS max_parallel_agents INTEGER",
        "ALTER TABLE factory_settings ADD COLUMN IF NOT EXISTS cursor_concurrent_limit INTEGER",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS base_branch VARCHAR(64) DEFAULT 'main'",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS work_branch VARCHAR(255)",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS isolate_branch BOOLEAN DEFAULT TRUE",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS merge_status VARCHAR(32)",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def run_instance_bootstrap() -> None:
    load_local_env_overrides()
    ensure_encryption_key()
    await _ensure_factory_settings_columns()
    async with SessionLocal() as session:
        from app.services.factory_settings import get_or_create_settings_row

        await get_or_create_settings_row(session)
        await refresh_api_key_cache(session)
