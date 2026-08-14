from unittest.mock import MagicMock

from app.services.deployment_urls import resolve_request_context


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
