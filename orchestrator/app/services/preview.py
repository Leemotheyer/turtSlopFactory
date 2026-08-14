import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_port_counter = settings.preview_port_start
_port_lock = asyncio.Lock()


def build_preview_url(port: int, host: str | None = None) -> str:
    host = (host or settings.public_host or settings.preview_host).rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        base = host
        if ":" in host.split("//", 1)[-1]:
            return f"{base}/"
        return f"{base}:{port}/"
    return f"http://{host}:{port}/"


def get_preview_port(meta: dict[str, Any]) -> int | None:
    port = meta.get("preview_port") or meta.get("staging_port")
    return int(port) if port else None


async def allocate_preview_port(meta: dict[str, Any]) -> int:
    existing = get_preview_port(meta)
    if existing:
        return existing

    global _port_counter
    async with _port_lock:
        port = _port_counter
        _port_counter += 1
        if _port_counter > settings.preview_port_end:
            _port_counter = settings.preview_port_start
        return port


def update_preview_metadata(
    meta: dict[str, Any],
    *,
    port: int,
    preview_type: str,
    status: str,
    container_id: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    url = build_preview_url(port, host=host)
    meta["preview_port"] = port
    meta["staging_port"] = port
    meta["preview_url"] = url
    meta["staging_url"] = url
    meta["preview_type"] = preview_type
    meta["preview_status"] = status
    if container_id:
        meta["preview_container_id"] = container_id
    return meta


def preview_from_metadata(meta: dict[str, Any], host: str | None = None) -> dict[str, Any]:
    port = get_preview_port(meta)
    url = meta.get("preview_url") or meta.get("staging_url")
    if port and not url:
        url = build_preview_url(port, host=host)
    return {
        "preview_url": url,
        "preview_port": port,
        "preview_type": meta.get("preview_type"),
        "preview_status": meta.get("preview_status"),
        "staging_url": url,
    }
