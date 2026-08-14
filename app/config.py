import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://turtslop:turtslop@db:5432/turtslop",
)
