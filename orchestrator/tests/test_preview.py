import pytest

from app.services.preview import (
    build_preview_url,
    get_preview_port,
    preview_from_metadata,
    update_preview_metadata,
)


def test_build_preview_url_localhost():
    assert build_preview_url(8081) == "http://localhost:8081/"


def test_build_preview_url_custom_host():
    from app.config import settings

    original = settings.preview_host
    settings.preview_host = "factory.example.com"
    try:
        assert build_preview_url(8090) == "http://factory.example.com:8090/"
    finally:
        settings.preview_host = original


def test_reuse_preview_port_from_metadata():
    meta = {"staging_port": 8085}
    assert get_preview_port(meta) == 8085


def test_update_preview_metadata_sets_urls():
    meta = {}
    update_preview_metadata(meta, port=8082, preview_type="dev", status="running", container_id="abc123")
    assert meta["preview_port"] == 8082
    assert meta["staging_port"] == 8082
    assert meta["preview_url"] == "http://localhost:8082/"
    assert meta["preview_type"] == "dev"
    assert meta["preview_status"] == "running"


def test_preview_from_metadata_back_compat():
    meta = {"staging_url": "http://localhost:8083/", "staging_port": 8083, "preview_type": "docker"}
    preview = preview_from_metadata(meta)
    assert preview["preview_url"] == "http://localhost:8083/"
    assert preview["preview_port"] == 8083
    assert preview["preview_type"] == "docker"
