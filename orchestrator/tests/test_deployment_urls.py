from unittest.mock import MagicMock

from app.services.deployment_urls import build_public_origin, resolve_request_context


def test_resolve_gateway_from_forwarded_headers():
    request = MagicMock()
    request.headers = {
        "x-forwarded-host": "factory.example.com",
        "x-forwarded-proto": "https",
    }
    request.url.scheme = "http"

    host, api_url, ws_url, gateway = resolve_request_context(request)
    assert host == "factory.example.com"
    assert api_url == "https://factory.example.com"
    assert ws_url == "wss://factory.example.com"
    assert gateway is True


def test_resolve_direct_localhost():
    request = MagicMock()
    request.headers = {"host": "localhost:8000"}
    request.url.scheme = "http"

    host, api_url, _, gateway = resolve_request_context(request)
    assert host == "localhost"
    assert api_url == "http://localhost:8000"
    assert gateway is False


def test_resolve_gateway_nonstandard_port():
    """Docker deploy on :8044 must not return internal API port :8000."""
    request = MagicMock()
    request.headers = {"host": "192.168.1.204:8044"}
    request.url.scheme = "http"

    host, api_url, ws_url, gateway = resolve_request_context(request)
    assert host == "192.168.1.204"
    assert api_url == "http://192.168.1.204:8044"
    assert ws_url == "ws://192.168.1.204:8044"
    assert gateway is True


def test_resolve_gateway_localhost_nonstandard_port():
    """localhost:8044 must use gateway mode, not internal :8000."""
    request = MagicMock()
    request.headers = {"host": "127.0.0.1:8044"}
    request.url.scheme = "http"

    host, api_url, ws_url, gateway = resolve_request_context(request)
    assert host == "127.0.0.1"
    assert api_url == "http://127.0.0.1:8044"
    assert ws_url == "ws://127.0.0.1:8044"
    assert gateway is True


def test_resolve_gateway_localhost_name_nonstandard_port():
    request = MagicMock()
    request.headers = {"host": "localhost:8044"}
    request.url.scheme = "http"

    host, api_url, _, gateway = resolve_request_context(request)
    assert host == "localhost"
    assert api_url == "http://localhost:8044"
    assert gateway is True


def test_resolve_gateway_localhost_without_port():
    """Host header localhost (no port) must still get :8044 in gateway mode."""
    request = MagicMock()
    request.headers = {"host": "localhost"}
    request.url.scheme = "http"

    host, api_url, ws_url, gateway = resolve_request_context(request)
    assert host == "localhost"
    assert api_url == "http://localhost:8044"
    assert ws_url == "ws://localhost:8044"
    assert gateway is True


def test_build_public_origin_localhost_adds_dashboard_port():
    assert build_public_origin("localhost") == "http://localhost:8044"


def test_build_public_origin_ip_without_port():
    assert build_public_origin("192.168.1.204") == "http://192.168.1.204:8044"


def test_build_public_origin_stored_host_port():
    assert build_public_origin("192.168.1.204:8044") == "http://192.168.1.204:8044"


def test_build_public_origin_domain_unchanged():
    assert build_public_origin("factory.example.com") == "http://factory.example.com"
