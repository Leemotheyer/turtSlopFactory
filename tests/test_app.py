from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "turtslopfactory"


def test_info():
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["name"] == "turtSlopFactory"


def test_create_and_list_items():
    r = client.post("/api/items", json={"title": "Test item", "body": "hello"})
    assert r.status_code == 201
    item = r.json()
    assert item["title"] == "Test item"

    r = client.get("/api/items")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_item_not_found():
    r = client.get("/api/items/99999")
    assert r.status_code == 404
