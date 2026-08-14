"""Reverse-proxy project live previews through the factory gateway."""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_models import ProjectRow
from app.services.preview import preview_path
from app.services.preview_manager import resolve_preview_upstream
from app.workspace.manager import WorkspaceManager

router = APIRouter(tags=["preview"])
workspace = WorkspaceManager()

_HOP_BY_HOP = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


async def _resolve_project_id(project_ref: str, db: AsyncSession) -> UUID:
    ref = project_ref.strip().lower()
    if len(ref) < 8:
        raise HTTPException(status_code=404, detail="Preview not found")
    result = await db.execute(select(ProjectRow.id))
    for (project_id,) in result.all():
        if str(project_id).lower().startswith(ref):
            return project_id
    raise HTTPException(status_code=404, detail="Preview not found")


def _inject_html_base(content: bytes, prefix: str) -> bytes:
    """Make relative URLs resolve under /preview/{id}/ for browser demos."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    lower = text.lower()
    if "<html" not in lower:
        return content
    base = f'<base href="{prefix}/">'
    if "<base " in lower:
        return content
    head_idx = lower.find("<head")
    if head_idx == -1:
        return content
    insert_at = lower.find(">", head_idx)
    if insert_at == -1:
        return content
    return (text[: insert_at + 1] + base + text[insert_at + 1 :]).encode("utf-8")


def _rewrite_location(location: str, *, prefix: str, upstream: str) -> str:
    if not location:
        return location
    upstream_base = upstream.rstrip("/")
    if location.startswith(upstream_base):
        rest = location[len(upstream_base) :] or "/"
        return prefix.rstrip("/") + (rest if rest.startswith("/") else f"/{rest}")
    parsed = urlparse(location)
    if parsed.scheme and parsed.netloc:
        return location
    if location.startswith("/"):
        return prefix.rstrip("/") + location
    return location


@router.api_route("/preview/{project_ref}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@router.api_route("/preview/{project_ref}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_preview(
    project_ref: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    path: str = "",
) -> Response:
    project_id = await _resolve_project_id(project_ref, db)
    prefix = preview_path(project_id).rstrip("/")
    if request.method in {"GET", "HEAD"} and not path and not str(request.url.path).endswith("/"):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(url=f"{prefix}/{query}", status_code=307)

    meta = workspace.load_metadata(project_id)
    upstream = await resolve_preview_upstream(project_id, meta)
    if not upstream:
        raise HTTPException(
            status_code=503,
            detail="Preview is not running. The factory will start it automatically during the pipeline.",
        )

    target_path = f"/{path}" if path else "/"
    target_url = f"{upstream.rstrip('/')}{target_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _HOP_BY_HOP
    }
    headers["X-Forwarded-Prefix"] = prefix
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto") or request.url.scheme

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
        if key.lower()
        not in ("content-encoding", "content-length", "transfer-encoding", "connection")
    }
    for key in list(response_headers):
        if key.lower() == "location":
            response_headers[key] = _rewrite_location(
                response_headers[key], prefix=prefix, upstream=upstream
            )

    content = upstream_response.content
    content_type = (upstream_response.headers.get("content-type") or "").lower()
    if "text/html" in content_type and content:
        content = _inject_html_base(content, prefix)

    return Response(
        content=content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
