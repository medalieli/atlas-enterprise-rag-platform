from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health_router)
app.include_router(documents_router)


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(RuntimeError)
async def readiness_error_handler(
    _: Request, __: SQLAlchemyError | RuntimeError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable", "database": "unavailable"},
    )


@app.get("/", tags=["application"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "environment": settings.app_env,
        "liveness": "/health/live",
        "readiness": "/health/ready",
        "docs": "/docs",
    }
