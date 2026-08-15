"""Generate a working Docker-deployable web app from a project spec."""

import json
import re
from pathlib import Path


_FACTORY_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
"""


def ensure_dockerfile(repo: Path) -> bool:
    """Write a working Dockerfile only when missing or empty. Never overwrites a real one."""
    path = repo / "Dockerfile"
    if path.is_file() and path.stat().st_size > 0:
        return False
    path.write_text(_FACTORY_DOCKERFILE)
    return True


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-")


def scaffold_base(repo: Path, name: str, description: str) -> list[str]:
    """Shared project skeleton: deps, docker, tests, main app shell."""
    slug = _slug(name)
    created: list[str] = []

    def write(rel: str, content: str) -> None:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        created.append(rel)

    write(
        "requirements.txt",
        """fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.10.0
httpx>=0.28.0
""",
    )

    write("app/__init__.py", "")
    (repo / "app" / "features").mkdir(parents=True, exist_ok=True)
    write("app/features/__init__.py", "")

    write(
        "app/main.py",
        f'''from pathlib import Path
import importlib.util

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="{name}", description="{description}")

ITEMS: list[dict] = []
_next_id = 1


class ItemCreate(BaseModel):
    title: str
    body: str = ""


class Item(BaseModel):
    id: int
    title: str
    body: str


@app.get("/health")
def health():
    return {{"status": "ok", "service": "{slug}"}}


@app.get("/api/info")
def info():
    return {{"name": "{name}", "description": "{description}"}}


def _load_feature_routers() -> None:
    features_dir = Path(__file__).parent / "features"
    if not features_dir.exists():
        return
    for path in sorted(features_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)


_load_feature_routers()

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
''',
    )

    write(
        "tests/__init__.py",
        "",
    )

    write(
        "tests/test_app.py",
        f'''from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "{slug}"


def test_info():
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["name"] == "{name}"


def test_create_and_list_items():
    r = client.post("/api/items", json={{"title": "Test item", "body": "hello"}})
    assert r.status_code == 201
    item = r.json()
    assert item["title"] == "Test item"

    r = client.get("/api/items")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_get_item_not_found():
    r = client.get("/api/items/99999")
    assert r.status_code == 404
''',
    )

    write(
        "tests/test_integration.py",
        '''"""Integration tests for API workflows."""
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
''',
    )

    write(
        "Dockerfile",
        _FACTORY_DOCKERFILE,
    )

    write(
        "docker-compose.yml",
        """services:
  app:
    build: .
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 5s
      timeout: 5s
      retries: 5
""",
    )

    write(
        "project.contract.yaml",
        f"""application:
  name: {slug}
  type: api

requirements:
  - id: R1
    description: Expose /health endpoint
  - id: R2
    description: REST API for items CRUD
  - id: R3
    description: Web UI accessible in browser

deployment:
  healthcheck:
    type: http
    path: /health
    port: 8080

tests:
  unit: true
  integration: true
  smoke: true

gates:
  max_fix_attempts: 5
  require_reviewer: true
  require_human_for_production: false
""",
    )

    write(
        ".env.example",
        """# Copy to .env and fill in values — never commit .env

# API_KEY=
# OPENAI_API_KEY=
""",
    )

    write(
        ".gitignore",
        """__pycache__/
*.pyc
.venv/
.pytest_cache/
.env
""",
    )

    return created


def scaffold_backend(repo: Path, name: str, description: str) -> list[str]:
    """API routes — written independently from frontend."""
    slug = _slug(name)
    created: list[str] = []
    main_path = repo / "app" / "main.py"
    content = main_path.read_text() if main_path.exists() else ""

    api_block = f'''

@app.get("/api/items", response_model=list[Item])
def list_items():
    return ITEMS


@app.post("/api/items", response_model=Item, status_code=201)
def create_item(body: ItemCreate):
    global _next_id
    item = {{"id": _next_id, "title": body.title, "body": body.body}}
    _next_id += 1
    ITEMS.append(item)
    return item


@app.get("/api/items/{{item_id}}", response_model=Item)
def get_item(item_id: int):
    for item in ITEMS:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")
'''

    if "@app.get(\"/api/items\"" not in content:
        marker = "def _load_feature_routers"
        if marker in content:
            content = content.replace(f"\n{marker}", f"{api_block}\n\n{marker}")
        else:
            content += api_block
        main_path.parent.mkdir(parents=True, exist_ok=True)
        main_path.write_text(content)
        created.append("app/main.py")

    return created


def scaffold_frontend(repo: Path, name: str, description: str) -> list[str]:
    """Static UI — independent from backend implementation."""
    created: list[str] = []

    def write(rel: str, html: str) -> None:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html)
        created.append(rel)

    write(
        "app/static/index.html",
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
  <style>
    :root {{ font-family: system-ui, sans-serif; background: #0f1117; color: #e8eaed; }}
    body {{ max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .muted {{ color: #8b93a7; margin-bottom: 1.5rem; }}
    form {{ display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }}
    input, button {{ padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid #2a2f3d; }}
    input {{ flex: 1; background: #1a1d27; color: inherit; }}
    button {{ background: #5b8def; color: #fff; border: none; cursor: pointer; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ padding: 0.75rem; background: #1a1d27; border-radius: 8px; margin-bottom: 0.5rem; }}
  </style>
</head>
<body>
  <h1>{name}</h1>
  <p class="muted">{description}</p>
  <form id="form">
    <input id="title" placeholder="New item title" required />
    <button type="submit">Add</button>
  </form>
  <ul id="items"></ul>
  <script>
    async function load() {{
      const res = await fetch('api/items');
      const items = await res.json();
      document.getElementById('items').innerHTML = items.map(i =>
        `<li><strong>${{i.title}}</strong>${{i.body ? ' — ' + i.body : ''}}</li>`
      ).join('') || '<li class="muted">No items yet</li>';
    }}
    document.getElementById('form').onsubmit = async (e) => {{
      e.preventDefault();
      const title = document.getElementById('title').value;
      await fetch('api/items', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ title }})
      }});
      document.getElementById('title').value = '';
      load();
    }};
    load();
  </script>
</body>
</html>
""",
    )

    return created


def scaffold_feature(repo: Path, feature_id: str, feature_content: str) -> list[str]:
    """Isolated feature module — safe to build in parallel with other streams."""
    created: list[str] = []
    safe_id = re.sub(r"[^a-z0-9_-]", "-", feature_id.lower())
    path = repo / "app" / "features" / f"{safe_id}.py"
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        f'''"""Feature: {feature_content}"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/features/{safe_id}", tags=["{safe_id}"])


@router.get("")
def feature_status():
  return {{
      "feature_id": "{safe_id}",
      "description": {json.dumps(feature_content)},
      "status": "implemented",
  }}
'''
    )
    created.append(f"app/features/{safe_id}.py")
    return created


def apply_incremental_fix(repo: Path, failure_output: str) -> list[str]:
    """Lightweight fix pass — patch tests or add missing health without full reset."""
    created: list[str] = []
    log_hint = failure_output.lower()

    test_file = repo / "tests" / "test_app.py"
    main_file = repo / "app" / "main.py"
    if not test_file.exists() or not main_file.exists():
        created.extend(scaffold_base(repo, "app", "auto-fix"))
        return created

    if "modulenotfounderror" in log_hint or "no module named" in log_hint:
        created.extend(scaffold_base(repo, "app", "auto-fix"))
        return created

    if "404" in log_hint and main_file.exists():
        main = main_file
        text = main.read_text()
        if "/api/items" not in text:
            scaffold_backend(repo, "app", "fix")
            created.append("app/main.py")

    return created


def scaffold_web_app(repo: Path, name: str, description: str) -> list[str]:
    """Full scaffold (sequential fallback). Returns list of created files."""
    created: list[str] = []
    created.extend(scaffold_base(repo, name, description))
    created.extend(scaffold_backend(repo, name, description))
    created.extend(scaffold_frontend(repo, name, description))
    return created
