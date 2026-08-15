from uuid import uuid4

from app.api.preview_proxy import _inject_html_base, _rewrite_location
from app.services.preview import preview_path


def test_rewrite_location_absolute_upstream():
    prefix = "/preview/deadbeef"
    upstream = "http://172.18.0.2:8080"
    assert _rewrite_location(f"{upstream}/api/items", prefix=prefix, upstream=upstream) == (
        "/preview/deadbeef/api/items"
    )


def test_rewrite_location_root_relative():
    assert _rewrite_location("/login", prefix="/preview/deadbeef", upstream="http://x:8080") == (
        "/preview/deadbeef/login"
    )


def test_inject_html_base_into_head():
    html = b"<html><head><title>App</title></head><body>hi</body></html>"
    out = _inject_html_base(html, "/preview/deadbeef")
    assert b'<base href="/preview/deadbeef/">' in out
    assert out.index(b"<head>") < out.index(b"<base")


def test_inject_html_base_skips_existing_base():
    html = b'<html><head><base href="/"></head></html>'
    assert _inject_html_base(html, "/preview/x") == html


def test_preview_path_matches_proxy_prefix():
    project_id = uuid4()
    assert preview_path(project_id).rstrip("/") == f"/preview/{str(project_id)[:8]}"
