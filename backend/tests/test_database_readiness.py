import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.api.health import database_readiness
from app.db.session import DatabaseReadiness, check_database_readiness
from app.main import app


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_DATABASE_TESTS") != "1",
    reason="set RUN_DATABASE_TESTS=1 with PostgreSQL/pgvector running",
)
async def test_database_and_pgvector_are_ready() -> None:
    readiness = await check_database_readiness()

    assert readiness.database == "ok"
    assert readiness.pgvector == "0.8.6"


@pytest.mark.asyncio
async def test_readiness_endpoint() -> None:
    async def ready_database() -> DatabaseReadiness:
        return DatabaseReadiness(database="ok", pgvector="0.8.6")

    app.dependency_overrides[database_readiness] = ready_database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "pgvector": "0.8.6",
    }


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_safe_failure() -> None:
    async def failed_database() -> DatabaseReadiness:
        raise OperationalError("SELECT 1", {}, Exception("secret connection details"))

    app.dependency_overrides[database_readiness] = failed_database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unavailable",
    }
    assert "secret" not in response.text
