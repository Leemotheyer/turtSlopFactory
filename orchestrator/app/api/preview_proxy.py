"""Reverse-proxy project live previews through the factory gateway."""

from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.services.preview_manager import resolve_preview_upstream
from app.workspace.manager import WorkspaceManager

router = APIRouter(tags=["preview"])
workspace = WorkspaceManager()


async def _resolve_project_id(project_ref: str, db: AsyncSession) -> UUID:
    ref = project_ref.strip().lower()
    if len(ref) < 8:
        raise HTTPException(status_code=404, detail="Preview not found")
    result = await db.execute(select(ProjectRow.id))
    for (project_id,) in result.all():
        if str(project_id).lower().startswith(ref):
            return project_id
    raise HTTPException(status_code=404, detail="Preview not found")


@router.api_route("/preview/{project_ref}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@router.api_route("/preview/{project_ref}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_preview(
    project_ref: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    path: str = "",
) -> Response:
    project_id = await _resolve_project_id(project_ref, db)
    meta = workspace.load_metadata(project_id)
    upstream = await resolve_preview_upstream(project_id, meta)
    if not upstream:
        raise HTTPException(status_code=503, detail="Preview is not running")

    target_path = f"/{path}" if path else "/"
    target_url = f"{upstream.rstrip('/')}{target_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in ("host", "content-length", "connection")
    }

    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:
        try:
            upstream_response = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body if body else None,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Preview unreachable: {exc}") from exc

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in ("content-encoding", "content-length", "transfer-encoding", "connection")
    }
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
