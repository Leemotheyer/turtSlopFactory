import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture(scope="session")
def client():
    from app.database import init_db
    from app.main import app

    asyncio.run(init_db())
    with TestClient(app) as test_client:
        yield test_client
