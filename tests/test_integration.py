"""Integration tests for API workflows."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_full_crud_flow():
    r = client.post("/api/items", json={"title": "A", "body": "first"})
    assert r.status_code == 201
    item_id = r.json()["id"]

    r = client.get(f"/api/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "A"

    r = client.get("/api/items")
    assert any(i["id"] == item_id for i in r.json())


def test_project_lifecycle():
    r = client.post(
        "/api/projects",
        json={"name": "Homelab Monitor", "idea": "Track docker containers"},
    )
    assert r.status_code == 201
    project = r.json()
    assert project["name"] == "Homelab Monitor"
    assert project["phase"] == "queued"
    assert len(project["events"]) >= 1

    r = client.get(f"/api/projects/{project['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == project["id"]

    r = client.get("/api/projects")
    assert r.status_code == 200
    assert any(p["id"] == project["id"] for p in r.json())
