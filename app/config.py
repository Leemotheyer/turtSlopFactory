import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./turtslopfactory.db",
)

SERVICE_NAME = "turtslopfactory"
SERVICE_TITLE = "turtSlopFactory"
SERVICE_DESCRIPTION = (
    "Self-hosted agentic software factory — start a project and let autonomous "
    "agents plan, implement, and iterate until a releasable Docker web app is ready."
)
