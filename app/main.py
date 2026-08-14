from contextlib import asynccontextmanager
from pathlib import Path
import importlib.util

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import SERVICE_DESCRIPTION, SERVICE_NAME, SERVICE_TITLE
from app.database import get_session, init_db
from app.db_models import Project, ProjectEvent
from app.schemas import (
    Item,
    ItemCreate,
    ProjectCreate,
    ProjectOut,
    ProjectSummary,
)
from app.services.agent_worker import worker

ITEMS: list[dict] = []
_next_item_id = 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    worker.start()
    yield
    await worker.stop()


app = FastAPI(title=SERVICE_TITLE, description=SERVICE_DESCRIPTION, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/api/info")
def info():
    return {"name": SERVICE_TITLE, "description": SERVICE_DESCRIPTION}


@app.get("/api/items", response_model=list[Item])
def list_items():
    return ITEMS


@app.post("/api/items", response_model=Item, status_code=201)
def create_item(body: ItemCreate):
    global _next_item_id
    item = {"id": _next_item_id, "title": body.title, "body": body.body}
    _next_item_id += 1
    ITEMS.append(item)
    return item


@app.get("/api/items/{item_id}", response_model=Item)
def get_item(item_id: int):
    for item in ITEMS:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")


@app.get("/api/projects", response_model=list[ProjectSummary])
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, session: AsyncSession = Depends(get_session)):
    project = Project(name=body.name.strip(), idea=body.idea.strip(), status="active", phase="queued")
    session.add(project)
    await session.flush()
    session.add(
        ProjectEvent(
            project_id=project.id,
            message="Project created — agents will begin planning shortly.",
            level="info",
        )
    )
    await session.commit()
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.events))
        .where(Project.id == project.id)
    )
    return result.scalar_one()


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.events))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/api/projects/{project_id}/advance", response_model=ProjectOut)
async def advance_project(project_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.events))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.phase == "ready":
        return project
    await worker._advance_project(session, project)
    await session.commit()
    result = await session.execute(
        select(Project)
        .options(selectinload(Project.events))
        .where(Project.id == project_id)
    )
    return result.scalar_one()


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
