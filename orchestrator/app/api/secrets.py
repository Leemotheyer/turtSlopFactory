from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.models import SecretSet
from app.services.secrets import delete_secret, list_secrets_public, set_secret

router = APIRouter(prefix="/projects", tags=["secrets"])


@router.get("/{project_id}/secrets")
async def get_secrets(project_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return await list_secrets_public(db, project_id)


@router.post("/{project_id}/secrets")
async def create_or_update_secret(
    project_id: UUID, body: SecretSet, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if not body.key_name.strip() or not body.value.strip():
        raise HTTPException(status_code=400, detail="key_name and value are required")
    return await set_secret(db, project_id, body.key_name, body.value, body.description)


@router.delete("/{project_id}/secrets/{key_name}")
async def remove_secret(
    project_id: UUID, key_name: str, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await db.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    if not await delete_secret(db, project_id, key_name):
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"status": "deleted", "key_name": key_name.upper()}
