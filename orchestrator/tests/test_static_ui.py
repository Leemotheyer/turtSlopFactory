import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    monkeypatch.setenv("FACTORY_CONFIG_DIR", str(tmp_path / "config"))
    from app.main import create_app

    return TestClient(create_app())


def test_static_ui_served(client):
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "turtSlopFactory" in r.text
    assert "text/html" in r.headers.get("content-type", "")


def test_static_assets_served(client):
    assert client.get("/ui/styles.css").status_code == 200
    assert client.get("/ui/app.js").status_code == 200


def test_static_ui_exempt_from_api_key(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key")
    r = client.get("/ui/")
    assert r.status_code == 200
