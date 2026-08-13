import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import events as events_api
from app.api import projects as projects_api
from app.api import tasks as tasks_api
from app.config import settings
from app.database import init_db
from app.events import event_bus
from app.models import FactoryEvent

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = event_bus.subscribe()
    try:
        while True:
            try:
                event: FactoryEvent = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(event.model_dump(mode="json"))
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await event_bus.connect()
    await init_db()

    redis_task = asyncio.create_task(_relay_redis_events())
    try:
        yield
    finally:
        redis_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await redis_task
        await event_bus.close()


async def _relay_redis_events() -> None:
    """Bridge Redis pub/sub into local subscriber queues (multi-instance fan-out)."""
    if not event_bus._redis:
        return
    async for event in event_bus.listen_redis():
        for queue in list(event_bus._subscribers):
            await queue.put(event)


def create_app() -> FastAPI:
    app = FastAPI(title="turtSlopFactory Control Plane", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(projects_api.router, prefix="/api")
    app.include_router(tasks_api.router, prefix="/api")
    app.include_router(events_api.router, prefix="/api")

    return app


app = create_app()
