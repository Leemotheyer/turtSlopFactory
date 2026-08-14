"""Preview contract: how the factory runs and probes a project container."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.services.preview import preview_path

DEFAULT_HEALTH_PATH = "/health"
DEFAULT_PREVIEW_PORT = 8080
PREVIEW_RUNTIME_IMAGE = "factory-preview-runtime:1"
PIP_CACHE_VOLUME = "factory-preview-pip"


@dataclass(frozen=True)
class PreviewHealthSpec:
    path: str = DEFAULT_HEALTH_PATH
    port: int = DEFAULT_PREVIEW_PORT


@dataclass(frozen=True)
class PreviewLaunch:
    success: bool
    message: str
    container_id: str | None = None
    container_name: str | None = None
    ephemeral_image: str | None = None
    backend: str = "docker"
    failure_kind: str | None = None  # "infra" | "app"


def load_preview_spec(repo: Path) -> PreviewHealthSpec:
    """Read healthcheck path/port from project.contract.yaml when present."""
    spec = PreviewHealthSpec()
    contract = repo / "project.contract.yaml"
    if not contract.is_file():
        return spec

    path = spec.path
    port = spec.port
    in_health = False
    health_indent: int | None = None
    for raw in contract.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip())
        content = stripped.strip()
        if content == "healthcheck:" or content.startswith("healthcheck:"):
            in_health = True
            health_indent = indent
            continue
        if in_health:
            if health_indent is not None and indent <= health_indent:
                in_health = False
            else:
                if content.startswith("path:"):
                    value = content.split(":", 1)[1].strip().strip("\"'")
                    if value:
                        path = value
                elif content.startswith("port:"):
                    value = content.split(":", 1)[1].strip()
                    try:
                        port = int(value)
                    except ValueError:
                        pass
                continue

    if not path.startswith("/"):
        path = f"/{path}"
    if port <= 0 or port > 65535:
        port = DEFAULT_PREVIEW_PORT
    return PreviewHealthSpec(path=path, port=port)


def gateway_preview_prefix(project_id: UUID) -> str:
    return preview_path(project_id).rstrip("/") or f"/preview/{str(project_id)[:8]}"


def detect_app_module(repo: Path) -> str:
    """ASGI target the factory runtime should start. Factory contract: app.main:app."""
    if (repo / "app" / "main.py").is_file():
        return "app.main:app"
    if (repo / "main.py").is_file():
        return "main:app"
    return "app.main:app"


def runtime_start_command(*, app_module: str, port: int, root_path: str) -> str:
    """Shell command run inside the factory-owned preview runtime."""
    root = root_path.strip() or "/"
    return (
        "mkdir -p /app && cd /app && "
        "if [ -f requirements.txt ]; then "
        "pip install --no-cache-dir -q -r requirements.txt; "
        "fi && "
        f"exec uvicorn {app_module} --host 0.0.0.0 --port {port} --root-path {root}"
    )
