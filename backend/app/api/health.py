from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.session import DatabaseReadiness, check_database_readiness

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    pgvector: str


async def database_readiness() -> DatabaseReadiness:
    return await check_database_readiness()


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(
    readiness: Annotated[DatabaseReadiness, Depends(database_readiness)],
) -> ReadyResponse:
    return ReadyResponse(
        status="ok",
        database=readiness.database,
        pgvector=readiness.pgvector,
    )
