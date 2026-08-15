import logging
from datetime import datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import EnvRequirementRow, ProjectSecretRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, NotificationType
from app.services.crypto import decrypt_value, encrypt_value, mask_value
from app.services.env_detection import detect_env_keys_from_texts
from app.services.notifications import create_notification

logger = logging.getLogger(__name__)


async def request_env_var(
    session: AsyncSession,
    project_id: UUID,
    key_name: str,
    description: str,
    requested_by: str = "agent",
) -> EnvRequirementRow:
    """Agent declares it needs an env var — value is NEVER seen by agents."""
    key_name = key_name.upper().strip()

    existing = await session.execute(
        select(EnvRequirementRow).where(
            EnvRequirementRow.project_id == project_id,
            EnvRequirementRow.key_name == key_name,
            EnvRequirementRow.status == "pending",
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        return row

    row = EnvRequirementRow(
        project_id=project_id,
        key_name=key_name,
        description=description,
        requested_by=requested_by,
        status="pending",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await create_notification(
        session,
        project_id,
        NotificationType.ENV_REQUIRED,
        f"Secret required: {key_name}",
        description or f"Configure {key_name} in project secrets. Agents cannot access this value.",
        action="secrets",
        reference_id=row.id,
    )

    await event_bus.publish(
        session,
        FactoryEvent(
            type=EventType.ENV_REQUIRED,
            project_id=project_id,
            payload={"key_name": key_name, "description": description},
        ),
    )
    return row


def _secret_has_value(encrypted: str) -> bool:
    try:
        return bool(decrypt_value(encrypted).strip())
    except Exception:
        return False


async def ensure_env_placeholder(
    session: AsyncSession,
    project_id: UUID,
    key_name: str,
    description: str,
    requested_by: str = "factory",
) -> None:
    """Create an empty secret slot + pending requirement so the user can fill the value."""
    key_name = key_name.upper().strip()

    secret_result = await session.execute(
        select(ProjectSecretRow).where(
            ProjectSecretRow.project_id == project_id,
            ProjectSecretRow.key_name == key_name,
        )
    )
    secret_row = secret_result.scalar_one_or_none()
    if secret_row and _secret_has_value(secret_row.encrypted_value):
        return

    if not secret_row:
        secret_row = ProjectSecretRow(
            project_id=project_id,
            key_name=key_name,
            encrypted_value=encrypt_value(""),
            description=description,
        )
        session.add(secret_row)
        await session.commit()
        await session.refresh(secret_row)

    await request_env_var(session, project_id, key_name, description, requested_by=requested_by)


async def scan_and_ensure_env_placeholders(
    session: AsyncSession,
    project_id: UUID,
    texts: Iterable[str],
    *,
    configured_keys: set[str] | None = None,
) -> list[str]:
    """Detect env keys from project text and ensure empty placeholders exist."""
    configured_keys = configured_keys or set()
    created: list[str] = []
    for key_name, description in detect_env_keys_from_texts(texts):
        if key_name in configured_keys:
            continue
        secret_result = await session.execute(
            select(ProjectSecretRow).where(
                ProjectSecretRow.project_id == project_id,
                ProjectSecretRow.key_name == key_name,
            )
        )
        row = secret_result.scalar_one_or_none()
        if row and _secret_has_value(row.encrypted_value):
            continue
        await ensure_env_placeholder(session, project_id, key_name, description)
        created.append(key_name)
    return created


def _is_invalid_work_branch(work_branch: str | None) -> bool:
    """Detect branches created before the project id was assigned."""
    return bool(work_branch and work_branch.rsplit("-", 1)[-1].lower() == "none")


async def get_github_token(session: AsyncSession, project_id: UUID) -> str | None:
    """Project secret first, then factory-stored token, then env."""
    from app.services.github_connection import resolve_github_token

    secrets = await get_secrets_for_runtime(session, project_id)
    token = secrets.get("GITHUB_TOKEN")
    if token:
        return token
    return await resolve_github_token(session)


async def maybe_request_github_token(session: AsyncSession, project_id: UUID, setup_message: str) -> None:
    if "GITHUB_TOKEN" not in setup_message:
        return
    if await get_github_token(session, project_id):
        return
    await request_env_var(
        session,
        project_id,
        "GITHUB_TOKEN",
        "GitHub personal access token with repo push access. "
        "Create one at https://github.com/settings/tokens (classic: repo scope). "
        "Or connect GitHub in the Cursor menu (factory-wide).",
        requested_by="factory",
    )


async def set_secret(
    session: AsyncSession,
    project_id: UUID,
    key_name: str,
    value: str,
    description: str = "",
) -> dict:
    key_name = key_name.upper().strip()
    encrypted = encrypt_value(value)

    existing = await session.execute(
        select(ProjectSecretRow).where(
            ProjectSecretRow.project_id == project_id,
            ProjectSecretRow.key_name == key_name,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.encrypted_value = encrypted
        row.description = description or row.description
        row.updated_at = datetime.utcnow()
    else:
        row = ProjectSecretRow(
            project_id=project_id,
            key_name=key_name,
            encrypted_value=encrypted,
            description=description,
        )
        session.add(row)

    reqs = await session.execute(
        select(EnvRequirementRow).where(
            EnvRequirementRow.project_id == project_id,
            EnvRequirementRow.key_name == key_name,
            EnvRequirementRow.status == "pending",
        )
    )
    for req in reqs.scalars():
        req.status = "fulfilled"
        req.fulfilled_at = datetime.utcnow()

    await session.commit()
    await session.refresh(row)

    return {
        "key_name": key_name,
        "masked_value": mask_value(value),
        "description": row.description,
        "configured": True,
    }


async def delete_secret(session: AsyncSession, project_id: UUID, key_name: str) -> bool:
    key_name = key_name.upper().strip()
    result = await session.execute(
        select(ProjectSecretRow).where(
            ProjectSecretRow.project_id == project_id,
            ProjectSecretRow.key_name == key_name,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def list_secrets_public(session: AsyncSession, project_id: UUID) -> dict:
    secrets_result = await session.execute(
        select(ProjectSecretRow).where(ProjectSecretRow.project_id == project_id)
    )
    secrets = []
    for row in secrets_result.scalars():
        try:
            plain = decrypt_value(row.encrypted_value)
            needs_value = not plain.strip()
            masked = "(not set — fill in on Secrets tab)" if needs_value else mask_value(plain)
        except Exception:
            needs_value = True
            masked = "****"
        secrets.append({
            "key_name": row.key_name,
            "masked_value": masked,
            "description": row.description,
            "configured": not needs_value,
            "needs_value": needs_value,
        })

    reqs_result = await session.execute(
        select(EnvRequirementRow)
        .where(EnvRequirementRow.project_id == project_id)
        .order_by(EnvRequirementRow.created_at.desc())
    )
    pending = []
    for row in reqs_result.scalars():
        if row.status == "pending":
            pending.append({
                "id": str(row.id),
                "key_name": row.key_name,
                "description": row.description,
                "requested_by": row.requested_by,
                "status": row.status,
            })

    return {
        "secrets": secrets,
        "pending_requirements": pending,
        "configured_keys": [s["key_name"] for s in secrets if s.get("configured")],
    }


async def get_secrets_for_runtime(session: AsyncSession, project_id: UUID) -> dict[str, str]:
    result = await session.execute(
        select(ProjectSecretRow).where(ProjectSecretRow.project_id == project_id)
    )
    env = {}
    for row in result.scalars():
        try:
            value = decrypt_value(row.encrypted_value)
            if value.strip():
                env[row.key_name] = value
        except Exception:
            logger.exception("Failed to decrypt %s for project %s", row.key_name, project_id)
    return env


async def get_env_status_for_agents(session: AsyncSession, project_id: UUID) -> dict:
    public = await list_secrets_public(session, project_id)
    return {
        "configured_keys": public["configured_keys"],
        "missing_keys": [r["key_name"] for r in public["pending_requirements"]],
        "note": "Secret values are managed by the user via the dashboard. Reference env vars by name only.",
    }
