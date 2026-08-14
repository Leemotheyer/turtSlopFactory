import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import EnvRequirementRow, ProjectSecretRow
from app.events import event_bus
from app.models import EventType, FactoryEvent, NotificationType
from app.services.crypto import decrypt_value, encrypt_value, mask_value
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


def _is_invalid_work_branch(work_branch: str | None) -> bool:
    """Detect branches created before the project id was assigned."""
    return bool(work_branch and work_branch.rsplit("-", 1)[-1].lower() == "none")


async def get_github_token(session: AsyncSession, project_id: UUID) -> str | None:
    """Project secret first, then factory-wide env / local.env."""
    import os

    secrets = await get_secrets_for_runtime(session, project_id)
    token = secrets.get("GITHUB_TOKEN")
    if token:
        return token
    return os.environ.get("GITHUB_TOKEN") or settings.github_token


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
        "Or set GITHUB_TOKEN in your factory local.env for all projects.",
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
            masked = mask_value(plain)
        except Exception:
            masked = "****"
        secrets.append({
            "key_name": row.key_name,
            "masked_value": masked,
            "description": row.description,
            "configured": True,
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
        "configured_keys": [s["key_name"] for s in secrets],
    }


async def get_secrets_for_runtime(session: AsyncSession, project_id: UUID) -> dict[str, str]:
    result = await session.execute(
        select(ProjectSecretRow).where(ProjectSecretRow.project_id == project_id)
    )
    env = {}
    for row in result.scalars():
        try:
            env[row.key_name] = decrypt_value(row.encrypted_value)
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
