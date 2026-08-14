import asyncio
import logging
from typing import Any
from uuid import UUID

from app.config import settings
from app.services.deployment_urls import build_public_origin

logger = logging.getLogger(__name__)

_port_counter = settings.preview_internal_port_start
_port_lock = asyncio.Lock()


def preview_path(project_id: UUID) -> str:
    return f"/preview/{str(project_id)[:8]}/"


def build_preview_url(
    project_id: UUID,
    *,
    origin: str | None = None,
    host: str | None = None,
) -> str:
    """Public URL for a project preview — always via the factory gateway path."""
    path = preview_path(project_id)
    if origin:
        return f"{origin.rstrip('/')}{path}"
    base = build_public_origin(
        host or settings.public_host or settings.preview_host,
        public_port=settings.dashboard_port,
    )
    return f"{base}{path}"


def preview_upstream(project_id: UUID, meta: dict[str, Any]) -> str | None:
    """Internal URL the API proxy uses to reach a running preview (sync fallback)."""
    backend = meta.get("preview_backend")
    if backend not in ("docker", "subprocess"):
        return None
    container = meta.get("preview_container") or meta.get("preview_container_id")
    if container and len(str(container)) <= 12:
        from app.services.preview_manager import preview_container_name

        container = preview_container_name(project_id)
    if container:
        return f"http://{container}:8080"
    return None


def get_preview_port(meta: dict[str, Any]) -> int | None:
    port = meta.get("preview_internal_port") or meta.get("preview_port") or meta.get("staging_port")
    return int(port) if port else None


async def allocate_preview_port(meta: dict[str, Any]) -> int:
    existing = get_preview_port(meta)
    if existing:
        return existing

    global _port_counter
    async with _port_lock:
        port = _port_counter
        _port_counter += 1
        if _port_counter > settings.preview_internal_port_end:
            _port_counter = settings.preview_internal_port_start
        return port


def update_preview_metadata(
    meta: dict[str, Any],
    *,
    project_id: UUID,
    port: int | None,
    preview_type: str,
    status: str,
    backend: str,
    origin: str | None = None,
    host: str | None = None,
    container_id: str | None = None,
    container_name: str | None = None,
    process_id: str | None = None,
    ephemeral_image: str | None = None,
) -> dict[str, Any]:
    url = build_preview_url(project_id, origin=origin, host=host)
    meta["preview_url"] = url
    meta["staging_url"] = url
    meta["preview_type"] = preview_type
    meta["preview_status"] = status
    meta["preview_backend"] = backend if status == "running" else None
    if port is not None:
        meta["preview_internal_port"] = port
        meta["preview_port"] = port
        meta["staging_port"] = port
    if status == "running":
        if container_id:
            meta["preview_container_id"] = container_id
        if container_name:
            meta["preview_container"] = container_name
        if ephemeral_image:
            meta["preview_ephemeral_image"] = ephemeral_image
        if process_id:
            meta["preview_process_id"] = process_id
    else:
        meta.pop("preview_container_id", None)
        meta.pop("preview_container", None)
        meta.pop("preview_ephemeral_image", None)
        meta.pop("preview_process_id", None)
        meta.pop("preview_internal_port", None)
        meta.pop("preview_port", None)
        meta.pop("staging_port", None)
    return meta


def preview_from_metadata(
    meta: dict[str, Any],
    *,
    origin: str | None = None,
    host: str | None = None,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    port = get_preview_port(meta)
    if project_id is not None:
        url = build_preview_url(project_id, origin=origin, host=host)
    else:
        url = meta.get("preview_url") or meta.get("staging_url")
    return {
        "preview_url": url,
        "preview_port": port,
        "preview_type": meta.get("preview_type"),
        "preview_status": meta.get("preview_status"),
        "staging_url": url,
    }
