import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "turtslopfactory"


@pytest.mark.asyncio
async def test_info(client):
    r = await client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["name"] == "turtSlopFactory"


@pytest.mark.asyncio
async def test_create_and_list_items(client):
    r = await client.post("/api/items", json={"title": "Test item", "body": "hello"})
    assert r.status_code == 201
    item = r.json()
    assert item["title"] == "Test item"

    r = await client.get("/api/items")
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_get_item_not_found(client):
    r = await client.get("/api/items/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_project(client):
    r = await client.post("/api/projects", json={"name": "Demo", "description": "A demo app"})
    assert r.status_code == 201
    project = r.json()
    assert project["name"] == "Demo"
    assert project["status"] in {"requested", "planning", "implementing", "testing", "review", "complete"}

    r = await client.get(f"/api/projects/{project['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == project["id"]
