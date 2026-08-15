from pathlib import Path
from uuid import uuid4

from app.services.preview_spec import (
    detect_app_module,
    gateway_preview_prefix,
    load_preview_spec,
    runtime_start_command,
)


def test_load_preview_spec_defaults(tmp_path: Path):
    spec = load_preview_spec(tmp_path)
    assert spec.path == "/health"
    assert spec.port == 8080


def test_load_preview_spec_from_contract(tmp_path: Path):
    (tmp_path / "project.contract.yaml").write_text(
        """application:
  name: demo
deployment:
  healthcheck:
    type: http
    path: /ready
    port: 9090
"""
    )
    spec = load_preview_spec(tmp_path)
    assert spec.path == "/ready"
    assert spec.port == 9090


def test_load_preview_spec_adds_leading_slash(tmp_path: Path):
    (tmp_path / "project.contract.yaml").write_text(
        "deployment:\n  healthcheck:\n    path: status\n"
    )
    spec = load_preview_spec(tmp_path)
    assert spec.path == "/status"


def test_detect_app_module(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("app = None\n")
    assert detect_app_module(tmp_path) == "app.main:app"


def test_runtime_start_command_uses_uvicorn_not_project_dockerfile():
    cmd = runtime_start_command(app_module="app.main:app", port=8080, root_path="/preview/deadbeef")
    assert "uvicorn app.main:app" in cmd
    assert "--port 8080" in cmd
    assert "--root-path /preview/deadbeef" in cmd
    assert "docker" not in cmd
    assert "pip install" in cmd


def test_gateway_preview_prefix():
    project_id = uuid4()
    assert gateway_preview_prefix(project_id) == f"/preview/{str(project_id)[:8]}"
