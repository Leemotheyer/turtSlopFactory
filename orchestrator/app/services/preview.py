import asyncio
import logging
from typing import Any
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)

_port_counter = settings.preview_internal_port_start
_port_lock = asyncio.Lock()


def preview_path(project_id: UUID) -> str:
    return f"/preview/{str(project_id)[:8]}/"


def build_preview_url(project_id: UUID, host: str | None = None) -> str:
    """Public URL for a project preview — always via the factory gateway path."""
    path = preview_path(project_id)
    host = (host or settings.public_host or settings.preview_host).strip()
    if host.startswith("http://") or host.startswith("https://"):
        base = host.rstrip("/")
        return f"{base}{path}"
    return f"http://{host.rstrip('/')}{path}"


def preview_upstream(project_id: UUID, meta: dict[str, Any]) -> str | None:
    """Internal URL the API proxy uses to reach a running preview."""
    backend = meta.get("preview_backend")
    if backend == "docker":
        container = meta.get("preview_container") or meta.get("preview_container_id")
        if container and len(str(container)) <= 12:
            from app.services.preview_manager import preview_container_name

            container = preview_container_name(project_id)
        if container:
            return f"http://{container}:8080"
        return None
    port = get_preview_port(meta)
    if port:
        return f"http://127.0.0.1:{port}"
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
    host: str | None = None,
    container_id: str | None = None,
    container_name: str | None = None,
    process_id: str | None = None,
) -> dict[str, Any]:
    url = build_preview_url(project_id, host=host)
    meta["preview_url"] = url
    meta["staging_url"] = url
    meta["preview_type"] = preview_type
    meta["preview_status"] = status
    meta["preview_backend"] = backend
    if port is not None:
        meta["preview_internal_port"] = port
        meta["preview_port"] = port
        meta["staging_port"] = port
    if container_id:
        meta["preview_container_id"] = container_id
    if container_name:
        meta["preview_container"] = container_name
    if process_id:
        meta["preview_process_id"] = process_id
    return meta


def preview_from_metadata(meta: dict[str, Any], host: str | None = None, project_id: UUID | None = None) -> dict[str, Any]:
    port = get_preview_port(meta)
    url = meta.get("preview_url") or meta.get("staging_url")
    if not url and project_id:
        url = build_preview_url(project_id, host=host)
    return {
        "preview_url": url,
        "preview_port": port,
        "preview_type": meta.get("preview_type"),
        "preview_status": meta.get("preview_status"),
        "staging_url": url,
    }
