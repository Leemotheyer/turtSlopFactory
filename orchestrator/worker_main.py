import asyncio
import logging

from app.config import settings
from app.database import init_db
from app.events import event_bus
from app.services.instance_bootstrap import run_instance_bootstrap
from app.worker import pipeline_queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    await run_instance_bootstrap()
    await event_bus.connect()
    await init_db()
    await pipeline_queue.connect()
    logger.info("Worker ready — processing pipeline queue")
    await pipeline_queue.process_loop()


if __name__ == "__main__":
    asyncio.run(main())
