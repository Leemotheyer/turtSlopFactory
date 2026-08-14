"""Integration tests for API workflows."""

import pytest


@pytest.mark.asyncio
async def test_full_crud_flow(client):
    r = await client.post("/api/items", json={"title": "A", "body": "first"})
    assert r.status_code == 201
    item_id = r.json()["id"]

    r = await client.get(f"/api/items/{item_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "A"

    r = await client.get("/api/items")
    assert any(i["id"] == item_id for i in r.json())


@pytest.mark.asyncio
async def test_project_events(client):
    r = await client.post("/api/projects", json={"description": "Worker service"})
    assert r.status_code == 201
    project_id = r.json()["id"]

    r = await client.get(f"/api/projects/{project_id}/events")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
