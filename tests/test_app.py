"""Factory pipeline unit tests — runnable from repo root."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("WORKER_ENABLED", "false")

from fastapi.testclient import TestClient


def test_health(api_client: TestClient):
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_info(api_client: TestClient):
    response = api_client.get("/api/settings/public")
    assert response.status_code == 200
    payload = response.json()
    assert "api_url" in payload


def test_create_and_list_items(api_client: TestClient):
    response = api_client.post("/api/items", json={"title": "Test item", "body": "hello"})
    assert response.status_code == 201
    item = response.json()
    assert item["title"] == "Test item"

    response = api_client.get("/api/items")
    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_get_item_not_found(api_client: TestClient):
    response = api_client.get("/api/items/99999")
    assert response.status_code == 404
