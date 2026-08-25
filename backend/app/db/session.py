from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@dataclass(frozen=True)
class DatabaseReadiness:
    database: str
    pgvector: str


engine: AsyncEngine = create_async_engine(
    get_settings().database_url,
    pool_pre_ping=True,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def check_database_readiness() -> DatabaseReadiness:
    """Verify database connectivity and return the installed pgvector version."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        version = await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    if version is None:
        raise RuntimeError("Required vector extension is not installed")

    return DatabaseReadiness(database="ok", pgvector=str(version))


async def dispose_engine() -> None:
    await engine.dispose()
