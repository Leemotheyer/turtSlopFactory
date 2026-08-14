from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import agents
from app.database import get_session, init_db
from app.models import Item, ItemCreate, Project, ProjectCreate, ProjectEvent
from app.models_db import EventRow, ItemRow, ProjectRow

APP_NAME = "turtSlopFactory"
APP_DESCRIPTION = (
    "Self-propelled agent factory for building releasable Docker web apps with minimal user input."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title=APP_NAME, description=APP_DESCRIPTION, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "turtslopfactory"}


@app.get("/api/info")
def info():
    return {
        "name": APP_NAME,
        "description": APP_DESCRIPTION,
        "features": [
            "self-propelled development agents",
            "project lifecycle automation",
            "mobile-friendly dashboard",
            "postgresql persistence",
        ],
    }


@app.get("/api/items", response_model=list[Item])
async def list_items(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ItemRow).order_by(ItemRow.id))
    rows = result.scalars().all()
    return [Item(id=r.id, title=r.title, body=r.body) for r in rows]


@app.post("/api/items", response_model=Item, status_code=201)
async def create_item(body: ItemCreate, session: AsyncSession = Depends(get_session)):
    row = ItemRow(title=body.title, body=body.body)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return Item(id=row.id, title=row.title, body=row.body)


@app.get("/api/items/{item_id}", response_model=Item)
async def get_item(item_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(ItemRow, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")
    return Item(id=row.id, title=row.title, body=row.body)


@app.get("/api/projects", response_model=list[Project])
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(ProjectRow).order_by(ProjectRow.id.desc()))
    rows = result.scalars().all()
    return [
        Project(
            id=r.id,
            name=r.name,
            description=r.description,
            status=r.status,
            iteration=r.iteration,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@app.post("/api/projects", response_model=Project, status_code=201)
async def create_project(body: ProjectCreate, session: AsyncSession = Depends(get_session)):
    name = body.name.strip() or f"Project {await _next_project_number(session)}"
    row = ProjectRow(name=name, description=body.description.strip(), status="requested")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    agents.start_project_pipeline(row.id)
    return Project(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        iteration=row.iteration,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.get("/api/projects/{project_id}", response_model=Project)
async def get_project(project_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return Project(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        iteration=row.iteration,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@app.post("/api/projects/{project_id}/start")
async def start_project(project_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    started = agents.start_project_pipeline(project_id)
    return {"project_id": project_id, "started": started, "running": agents.is_running(project_id)}


@app.get("/api/projects/{project_id}/events", response_model=list[ProjectEvent])
async def project_events(project_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(ProjectRow, project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await session.execute(
        select(EventRow)
        .where(EventRow.project_id == project_id)
        .order_by(EventRow.id.desc())
        .limit(50)
    )
    events = result.scalars().all()
    return [
        ProjectEvent(
            id=e.id,
            project_id=e.project_id,
            message=e.message,
            created_at=e.created_at,
        )
        for e in events
    ]


async def _next_project_number(session: AsyncSession) -> int:
    result = await session.execute(select(ProjectRow.id))
    return len(result.scalars().all()) + 1


static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
