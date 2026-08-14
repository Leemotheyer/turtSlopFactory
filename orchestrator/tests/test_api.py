"""API route tests — health check, item CRUD, and project CRUD."""

from uuid import UUID


def test_health(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "1.0.0"


def test_create_and_list_items(api_client):
    create = api_client.post("/api/items", json={"title": "Test item", "body": "hello"})
    assert create.status_code == 201
    item = create.json()
    assert item["title"] == "Test item"
    assert item["body"] == "hello"
    assert isinstance(item["id"], int)

    listing = api_client.get("/api/items")
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    assert items[0]["title"] == "Test item"


def test_get_item(api_client):
    created = api_client.post("/api/items", json={"title": "Lookup", "body": "find me"})
    item_id = created.json()["id"]

    response = api_client.get(f"/api/items/{item_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Lookup"


def test_get_item_not_found(api_client):
    response = api_client.get("/api/items/99999")
    assert response.status_code == 404


def test_update_item(api_client):
    created = api_client.post("/api/items", json={"title": "Before", "body": "old"})
    item_id = created.json()["id"]

    response = api_client.patch(
        f"/api/items/{item_id}",
        json={"title": "After", "body": "new"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "After"
    assert response.json()["body"] == "new"


def test_delete_item(api_client):
    created = api_client.post("/api/items", json={"title": "Temporary", "body": ""})
    item_id = created.json()["id"]

    deleted = api_client.delete(f"/api/items/{item_id}")
    assert deleted.status_code == 204

    missing = api_client.get(f"/api/items/{item_id}")
    assert missing.status_code == 404


def test_full_crud_flow(api_client):
    created = api_client.post("/api/items", json={"title": "A", "body": "first"})
    assert created.status_code == 201
    item_id = created.json()["id"]

    fetched = api_client.get(f"/api/items/{item_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "A"

    listed = api_client.get("/api/items")
    assert any(item["id"] == item_id for item in listed.json())


def test_create_and_list_projects(api_client):
    response = api_client.post(
        "/api/projects",
        json={"name": "Demo App", "description": "A sample factory project"},
    )
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Demo App"
    assert project["state"] == "REQUESTED"
    project_id = project["id"]

    listing = api_client.get("/api/projects")
    assert listing.status_code == 200
    assert any(row["id"] == project_id for row in listing.json())


def test_get_project_not_found(api_client):
    response = api_client.get(f"/api/projects/{UUID(int=0)}")
    assert response.status_code == 404


def test_update_project(api_client):
    created = api_client.post(
        "/api/projects",
        json={"name": "Original", "description": "First draft"},
    )
    project_id = created.json()["id"]

    updated = api_client.patch(
        f"/api/projects/{project_id}",
        json={"branch": "develop"},
    )
    assert updated.status_code == 200
    assert updated.json()["branch"] == "develop"


def test_delete_project(api_client):
    created = api_client.post(
        "/api/projects",
        json={"name": "Disposable", "description": "Remove me"},
    )
    project_id = created.json()["id"]

    deleted = api_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    missing = api_client.get(f"/api/projects/{project_id}")
    assert missing.status_code == 404
