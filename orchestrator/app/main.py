import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import contracts as contracts_api
from app.api import cursor as cursor_api
from app.api import github as github_api
from app.api import discovery as discovery_api
from app.api import events as events_api
from app.api import feedback as feedback_api
from app.api import notifications as notifications_api
from app.api import pipeline as pipeline_api
from app.api import preview_proxy as preview_proxy_api
from app.api import projects as projects_api
from app.api import secrets as secrets_api
from app.api import settings as settings_api
from app.api import tasks as tasks_api
from app.config import settings
from app.database import SessionLocal, init_db
from app.events import event_bus
from app.middleware import APIKeyMiddleware
from app.models import FactoryEvent
from app.services.discovery import auto_submit_expired_intake
from app.services.input_requests import expire_stale_requests
from app.services.instance_bootstrap import run_instance_bootstrap
from app.services.pipeline_control import reconcile_stale_running_tasks
from app.services.preview_manager import (
    cleanup_orphan_preview_resources,
    ensure_preview_network,
    warmup_preview_runtime,
)
from app.worker import pipeline_queue

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


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


async def _expire_input_requests_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            async with SessionLocal() as session:
                await expire_stale_requests(session)
                await auto_submit_expired_intake(session)
        except Exception:
            pass


async def _post_production_scheduler_loop() -> None:
    """Periodically start due self-propelling post-production cycles."""
    from app.services.self_propelling import scan_due_post_production_projects

    while True:
        await asyncio.sleep(1800)
        try:
            async with SessionLocal() as session:
                scheduled = await scan_due_post_production_projects(session)
                if scheduled:
                    logger.info("Scheduled %s post-production cycle(s)", scheduled)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await run_instance_bootstrap()
    async with SessionLocal() as session:
        await reconcile_stale_running_tasks(session)
    ensure_preview_network()
    await cleanup_orphan_preview_resources()
    asyncio.create_task(warmup_preview_runtime())
    await event_bus.connect()
    await pipeline_queue.connect()

    redis_task = asyncio.create_task(_relay_redis_events())
    expire_task = asyncio.create_task(_expire_input_requests_loop())
    post_production_task = asyncio.create_task(_post_production_scheduler_loop())
    worker_task = None
    if settings.worker_enabled:
        worker_task = asyncio.create_task(pipeline_queue.process_loop())

    try:
        yield
    finally:
        redis_task.cancel()
        expire_task.cancel()
        post_production_task.cancel()
        if worker_task:
            worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await redis_task
            await expire_task
            await post_production_task
            if worker_task:
                await worker_task
        await pipeline_queue.close()
        await event_bus.close()


async def _relay_redis_events() -> None:
    """Bridge Redis pub/sub into local subscriber queues (multi-instance fan-out)."""
    if not event_bus._redis:
        return
    async for event in event_bus.listen_redis():
        for queue in list(event_bus._subscribers):
            await queue.put(event)


def create_app() -> FastAPI:
    app = FastAPI(title="turtSlopFactory Control Plane", version="1.0.0", lifespan=lifespan)

    app.add_middleware(APIKeyMiddleware)
    cors_origins = ["*"] if settings.cors_allow_all else settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=not settings.cors_allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    app.include_router(preview_proxy_api.router)
    app.include_router(projects_api.router, prefix="/api")
    app.include_router(contracts_api.router, prefix="/api")
    app.include_router(tasks_api.router, prefix="/api")
    app.include_router(events_api.router, prefix="/api")
    app.include_router(pipeline_api.router, prefix="/api")
    app.include_router(feedback_api.router, prefix="/api")
    app.include_router(discovery_api.router, prefix="/api")
    app.include_router(secrets_api.router, prefix="/api")
    app.include_router(notifications_api.router, prefix="/api")
    app.include_router(cursor_api.router, prefix="/api")
    app.include_router(github_api.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")

    return app


app = create_app()
