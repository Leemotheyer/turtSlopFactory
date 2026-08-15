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


def _should_append_public_port(hostname: str, port: int | None) -> bool:
    """Add :8044-style ports for local/IP gateway deploys, not for public domain names."""
    if not port or port in (80, 443):
        return False
    if hostname in ("localhost", "127.0.0.1"):
        return True
    parts = hostname.split(".")
    if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
        return True
    return False


def _gateway_origin(host_header: str, *, scheme: str = "http") -> str:
    """Browser-reachable gateway origin; adds :8044-style port for local/IP hosts when omitted."""
    hostname, port = _split_host_port(host_header)
    if port is not None:
        return f"{scheme}://{host_header}".rstrip("/")
    return build_public_origin(host_header, scheme=scheme, public_port=settings.dashboard_port)


def build_public_origin(
    host: str,
    *,
    scheme: str = "http",
    public_port: int | None = None,
) -> str:
    """Build a browser-reachable origin, including non-standard ports (e.g. :8044)."""
    from app.config import settings

    host = host.strip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    hostname, port = _split_host_port(host)
    effective_public_port = public_port if public_port is not None else settings.dashboard_port
    if port is None and _should_append_public_port(hostname, effective_public_port):
        port = effective_public_port
    if port is None or port in (80, 443):
        return f"{scheme}://{hostname}".rstrip("/")
    return f"{scheme}://{hostname}:{port}".rstrip("/")


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
        hostname, port = _split_host_port(host_header)
        ws_scheme = "wss" if scheme == "https" else "ws"
        api_url = _gateway_origin(host_header, scheme=scheme)
        ws_url = f"{ws_scheme}://{host_header}".rstrip("/")
        if port is None:
            _, ws_port = _split_host_port(api_url.replace(f"{scheme}://", "", 1))
            if ws_port:
                ws_url = f"{ws_scheme}://{hostname}:{ws_port}"
        return hostname, api_url, ws_url, True

    host_header = request.headers.get("host") or default_host
    scheme = request.url.scheme
    hostname, port = _split_host_port(host_header)

    # Standard HTTP(S) ports or any non-API port (e.g. 8044) — single-origin gateway deploy
    is_gateway_port = port in (80, 443, None) or (port is not None and port != settings.api_port)
    if is_gateway_port:
        api_url = _gateway_origin(host_header, scheme=scheme)
        ws_scheme = "wss" if scheme == "https" else "ws"
        ws_host = host_header
        if port is None:
            _, ws_port = _split_host_port(api_url.replace(f"{scheme}://", "", 1))
            if ws_port:
                ws_host = f"{hostname}:{ws_port}"
        return hostname, api_url, f"{ws_scheme}://{ws_host}".rstrip("/"), True

    preview_host = default_host if hostname in ("localhost", "127.0.0.1") else hostname
    api_url = f"http://{preview_host}:{settings.api_port}"
    ws_url = f"ws://{preview_host}:{settings.api_port}"
    return preview_host, api_url, ws_url, False


async def maybe_auto_configure(
    session: AsyncSession, row: FactorySettingsRow, request: Request | None
) -> FactorySettingsRow:
    if row.setup_complete or request is None:
        return row

    hostname, api_url, _, gateway = resolve_request_context(request)
    if hostname in ("localhost", "127.0.0.1"):
        return row

    # Persist host:port (or full forwarded host) so preview links match the gateway URL.
    if gateway:
        host_header = request.headers.get("x-forwarded-host") or request.headers.get("host")
        row.preview_host = (host_header or hostname).split(",")[0].strip()
    else:
        row.preview_host = hostname
    row.setup_complete = True
    await session.commit()
    await session.refresh(row)
    return row
