from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest, token_hex
from time import perf_counter

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from opentelemetry import propagate, trace
from sqlalchemy.exc import SQLAlchemyError

from app.api.answers import router as answers_router
from app.api.conversations import router as conversations_router
from app.api.documents import router as documents_router
from app.api.enterprise import router as enterprise_router
from app.api.health import router as health_router
from app.api.identity import router as identity_router
from app.api.lifecycle import router as lifecycle_router
from app.api.search import router as search_router
from app.core.config import get_settings
from app.db.session import dispose_engine
from app.observability import (
    begin_http,
    configure,
    metrics_payload,
    observe_http,
    request_id_var,
    tracer,
)
from app.reranking import warm_reranker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await warm_reranker()
    yield
    await dispose_engine()


settings = get_settings()
configure(settings)
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(answers_router)
app.include_router(conversations_router)
app.include_router(health_router)
app.include_router(identity_router)
app.include_router(lifecycle_router)
app.include_router(documents_router)
app.include_router(enterprise_router)
app.include_router(search_router)


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    route, method, started = begin_http(request.url.path, request.method)
    request_token = request_id_var.set(token_hex(8))
    parent = propagate.extract(dict(request.headers))
    status_code = 500
    try:
        with tracer().start_as_current_span(
            "http.server.request",
            context=parent,
            kind=trace.SpanKind.SERVER,
            attributes={"http.request.method": method, "http.route": route},
        ) as span:
            response = await call_next(request)
            status_code = response.status_code
            span.set_attribute("http.response.status_code", status_code)
            response.headers["x-request-id"] = request_id_var.get()
            response.headers["Cache-Control"] = response.headers.get(
                "Cache-Control", "private, no-store"
            )
            return response
    finally:
        observe_http(route, method, status_code, perf_counter() - started)
        request_id_var.reset(request_token)


@app.get("/internal/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    expected = settings.metrics_bearer_token
    supplied = request.headers.get("authorization", "")
    valid = expected is not None and compare_digest(
        supplied, f"Bearer {expected.get_secret_value()}"
    )
    if not settings.metrics_enabled or not valid:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    body, content_type = metrics_payload()
    return Response(
        body, media_type=content_type, headers={"Cache-Control": "no-store"}
    )


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
