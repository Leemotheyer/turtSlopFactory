"""Resolve public URLs and auto-configure deployment from incoming requests."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db_models import FactorySettingsRow


def _split_host_port(host_header: str) -> tuple[str, int | None]:
    host_header = host_header.split(",")[0].strip()
    if host_header.startswith("["):
        if "]:" in host_header:
            host, port_s = host_header.rsplit("]:", 1)
            return host.strip("[]"), int(port_s)
        return host_header.strip("[]"), None
    if ":" in host_header:
        host, port_s = host_header.rsplit(":", 1)
        if port_s.isdigit():
            return host, int(port_s)
    return host_header, None


def resolve_request_context(request: Request | None) -> tuple[str, str, str, bool]:
    """Return preview_host, api_url, ws_url, gateway_mode."""
    default_host = settings.public_host or settings.preview_host
    if request is None or not settings.trust_proxy_headers:
        api_url = f"http://{default_host}:{settings.api_port}"
        return default_host, api_url, f"ws://{default_host}:{settings.api_port}", False

    forwarded = request.headers.get("x-forwarded-host")
    if forwarded:
        host_header = forwarded.split(",")[0].strip()
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        hostname, _ = _split_host_port(host_header)
        ws_scheme = "wss" if scheme == "https" else "ws"
        api_url = f"{scheme}://{host_header}".rstrip("/")
        ws_url = f"{ws_scheme}://{host_header}".rstrip("/")
        return hostname, api_url, ws_url, True

    host_header = request.headers.get("host") or default_host
    scheme = request.url.scheme
    hostname, port = _split_host_port(host_header)

    # Standard HTTP(S) ports or any non-API port (e.g. 8044) — single-origin gateway deploy
    is_gateway_port = port in (80, 443, None) or (port is not None and port != settings.api_port)
    if is_gateway_port:
        api_url = f"{scheme}://{host_header}".rstrip("/")
        ws_scheme = "wss" if scheme == "https" else "ws"
        return hostname, api_url, f"{ws_scheme}://{host_header}".rstrip("/"), True

    preview_host = default_host if hostname in ("localhost", "127.0.0.1") else hostname
    api_url = f"http://{preview_host}:{settings.api_port}"
    ws_url = f"ws://{preview_host}:{settings.api_port}"
    return preview_host, api_url, ws_url, False


async def maybe_auto_configure(
    session: AsyncSession, row: FactorySettingsRow, request: Request | None
) -> FactorySettingsRow:
    if row.setup_complete or request is None:
        return row

    hostname, _, _, _ = resolve_request_context(request)
    if hostname in ("localhost", "127.0.0.1"):
        return row

    row.preview_host = hostname
    row.setup_complete = True
    await session.commit()
    await session.refresh(row)
    return row
