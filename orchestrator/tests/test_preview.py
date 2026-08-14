from uuid import uuid4

import pytest

from app.services.preview import (
    build_preview_url,
    get_preview_port,
    preview_path,
    preview_from_metadata,
    update_preview_metadata,
)


def test_preview_path():
    project_id = uuid4()
    assert preview_path(project_id) == f"/preview/{str(project_id)[:8]}/"


def test_build_preview_url_uses_gateway_path_with_local_port():
    project_id = uuid4()
    assert (
        build_preview_url(project_id)
        == f"http://localhost:8044/preview/{str(project_id)[:8]}/"
    )


def test_build_preview_url_explicit_origin():
    project_id = uuid4()
    assert (
        build_preview_url(project_id, origin="http://192.168.1.204:8044")
        == f"http://192.168.1.204:8044/preview/{str(project_id)[:8]}/"
    )


def test_build_preview_url_custom_host_with_port():
    from app.config import settings

    project_id = uuid4()
    original = settings.preview_host
    settings.preview_host = "192.168.1.204:8044"
    try:
        assert (
            build_preview_url(project_id)
            == f"http://192.168.1.204:8044/preview/{str(project_id)[:8]}/"
        )
    finally:
        settings.preview_host = original


def test_build_preview_url_domain_without_extra_port():
    from app.config import settings

    project_id = uuid4()
    original = settings.preview_host
    settings.preview_host = "factory.example.com"
    try:
        assert (
            build_preview_url(project_id)
            == f"http://factory.example.com/preview/{str(project_id)[:8]}/"
        )
    finally:
        settings.preview_host = original


def test_reuse_preview_internal_port_from_metadata():
    meta = {"preview_internal_port": 10015}
    assert get_preview_port(meta) == 10015


def test_update_preview_metadata_sets_gateway_url():
    project_id = uuid4()
    meta = {}
    update_preview_metadata(
        meta,
        project_id=project_id,
        port=10012,
        preview_type="dev",
        status="running",
        backend="subprocess",
        origin="http://192.168.1.204:8044",
        process_id="1234",
    )
    assert meta["preview_internal_port"] == 10012
    assert meta["preview_url"] == f"http://192.168.1.204:8044/preview/{str(project_id)[:8]}/"
    assert meta["preview_backend"] == "subprocess"


def test_update_preview_metadata_clears_runtime_on_failure():
    project_id = uuid4()
    meta = {
        "preview_container": "factory-live-deadbeef",
        "preview_container_id": "abc123",
    }
    update_preview_metadata(
        meta,
        project_id=project_id,
        port=None,
        preview_type="docker",
        status="failed",
        backend="docker",
        container_id="abc123",
        container_name="factory-live-deadbeef",
    )
    assert meta.get("preview_backend") is None
    assert "preview_container" not in meta


def test_preview_from_metadata_rebuilds_url():
    project_id = uuid4()
    meta = {
        "preview_url": f"http://192.168.1.204/preview/{str(project_id)[:8]}/",
        "preview_internal_port": 10013,
        "preview_type": "docker",
    }
    preview = preview_from_metadata(
        meta,
        origin="http://192.168.1.204:8044",
        project_id=project_id,
    )
    assert preview["preview_url"] == f"http://192.168.1.204:8044/preview/{str(project_id)[:8]}/"
    assert preview["preview_port"] == 10013
    assert preview["preview_type"] == "docker"
