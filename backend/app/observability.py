from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter

from opentelemetry import context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.config import Settings

SAFE_ROUTES = frozenset(
    {
        "/",
        "/health/live",
        "/health/ready",
        "/internal/metrics",
        "/auth/me",
        "/collections",
        "/collections/{collection_id}",
        "/collections/{collection_id}/documents",
        "/collections/{collection_id}/documents/{document_id}",
        "/collections/{collection_id}/documents/{document_id}/versions",
        "/collections/{collection_id}/documents/{document_id}/versions/{version_id}",
        "/collections/{collection_id}/documents/{document_id}/versions/{version_id}/source",
        "/collections/{collection_id}/documents/{document_id}/reindex",
        "/collections/{collection_id}/conversations",
        "/collections/{collection_id}/conversations/{conversation_id}",
        "/collections/{collection_id}/conversations/{conversation_id}/messages",
        "/processing-jobs/{job_id}",
        "/collections/{collection_id}/semantic-search",
        "/collections/{collection_id}/keyword-search",
        "/collections/{collection_id}/hybrid-search",
        "/collections/{collection_id}/reranked-search",
        "/collections/{collection_id}/ask",
    }
)
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
STATUS_CLASSES = frozenset({"2xx", "3xx", "4xx", "5xx"})
RETRIEVAL_MODES = frozenset({"keyword", "semantic", "hybrid", "reranked"})
OPERATIONS = frozenset(
    {
        "ingestion",
        "replacement",
        "reindex",
        "deletion",
        "rewrite",
        "answer",
        "evaluation",
    }
)
OUTCOMES = frozenset(
    {
        "succeeded",
        "failed",
        "retrying",
        "cancelled",
        "answered",
        "insufficient_context",
        "conflicting_sources",
        "clarification_required",
    }
)
ERROR_CATEGORIES = frozenset(
    {
        "none",
        "authentication",
        "authorization",
        "validation",
        "rate_limit",
        "quota",
        "timeout",
        "network",
        "provider",
        "storage",
        "database",
        "internal",
    }
)
SPAN_NAMES = frozenset(
    {
        "http.server.request",
        "celery.task.execute",
        "ingestion.job.execute",
        "storage.source.verify",
        "ingestion.parse",
        "ingestion.clean_chunk",
        "provider.embedding.request",
        "retrieval.semantic.candidates",
        "retrieval.keyword.candidates",
        "retrieval.hybrid.fusion",
        "retrieval.rerank",
        "conversation.followup.rewrite",
        "answer.generate",
        "answer.citations.validate",
        "lifecycle.replacement.enqueue",
        "lifecycle.reindex.enqueue",
        "lifecycle.deletion.execute",
    }
)
_SECRET_PATTERN = re.compile(
    r"(?i)Bearer\s+\S+|"
    r"(authorization|cookie|api[_-]?key|access[_-]?token|refresh[_-]?token)"
    r"\s*[:=]\s*(?:Bearer\s+)?\S+|sk-[A-Za-z0-9_-]{20,}"
)

HTTP_REQUESTS = Counter(
    "rag_http_requests_total", "HTTP requests.", ["route", "method", "status_class"]
)
HTTP_ACTIVE = Gauge(
    "rag_http_active_requests", "Active HTTP requests.", ["route", "method"]
)
HTTP_DURATION = Histogram(
    "rag_http_request_duration_seconds",
    "HTTP request duration.",
    ["route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_stage_duration_seconds",
    "Retrieval stage duration.",
    ["mode"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
RETRIEVAL_RESULTS = Histogram(
    "rag_retrieval_results",
    "Retrieved candidate count.",
    ["mode"],
    buckets=(0, 1, 2, 4, 8, 16, 32, 64),
)
INGESTION_JOBS = Counter(
    "rag_ingestion_jobs_total", "Ingestion job outcomes.", ["operation", "outcome"]
)
INGESTION_DURATION = Histogram(
    "rag_ingestion_duration_seconds",
    "Ingestion duration.",
    ["operation"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
INGESTION_QUEUE = Gauge(
    "rag_ingestion_queued_jobs", "Queued ingestion jobs.", ["operation"]
)
PROVIDER_REQUESTS = Counter(
    "rag_provider_requests_total",
    "Provider request outcomes.",
    ["operation", "provider", "model", "error_category"],
)
PROVIDER_DURATION = Histogram(
    "rag_provider_request_duration_seconds",
    "Provider request duration.",
    ["operation", "provider", "model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
PROVIDER_TOKENS = Counter(
    "rag_provider_tokens_total",
    "Provider tokens.",
    ["operation", "provider", "model", "direction"],
)
ANSWER_STATUS = Counter(
    "rag_answer_status_total", "Grounded answer statuses.", ["status"]
)
CITATION_FAILURES = Counter(
    "rag_citation_validation_failures_total",
    "Citation validation failures.",
    ["error_category"],
)
LIFECYCLE = Counter(
    "rag_lifecycle_operations_total",
    "Lifecycle operation outcomes.",
    ["operation", "outcome"],
)
EVALUATION_RUNS = Counter(
    "rag_evaluation_runs_total", "Evaluation run outcomes.", ["kind", "outcome"]
)
EVALUATION_DURATION = Histogram(
    "rag_evaluation_duration_seconds",
    "Evaluation duration.",
    ["kind"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300),
)

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def bounded(value: str, allowed: frozenset[str], fallback: str) -> str:
    return value if value in allowed else fallback


def configured_model_label(value: str, configured: str) -> str:
    """Keep the label bounded even if a provider returns a surprising model name."""
    return configured if value == configured else "other"


def route_label(path: str) -> str:
    if path in SAFE_ROUTES:
        return path
    for template in SAFE_ROUTES:
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", template)
        if re.fullmatch(pattern, path):
            return template
    return "unmatched"


def span_ids() -> tuple[str, str]:
    span = trace.get_current_span().get_span_context()
    if not span.is_valid:
        return "", ""
    return f"{span.trace_id:032x}", f"{span.span_id:016x}"


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = span_ids()
        message = _SECRET_PATTERN.sub("[REDACTED]", record.getMessage())
        return json.dumps(
            {
                "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
                "level": record.levelname.lower(),
                "logger": record.name,
                "message": message,
                "request_id": request_id_var.get(),
                "trace_id": trace_id,
                "span_id": span_id,
            },
            separators=(",", ":"),
        )


def configure(settings: Settings) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(SafeJsonFormatter())
    for name in ("uvicorn.error", "rag"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
    if settings.telemetry_enabled and not isinstance(
        trace.get_tracer_provider(), TracerProvider
    ):
        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: settings.service_name})
        )
        exporter = OTLPSpanExporter(
            endpoint=f"{settings.otel_exporter_otlp_endpoint.rstrip('/')}/v1/traces",
            timeout=3,
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=512,
                max_export_batch_size=128,
                export_timeout_millis=3000,
            )
        )
        trace.set_tracer_provider(provider)


def tracer():
    return trace.get_tracer("production-rag-assistant")


@contextmanager
def stage(
    name: str, attributes: dict[str, str | int | float] | None = None
) -> Iterator[None]:
    if name not in SPAN_NAMES:
        raise ValueError("span name is not registered")
    safe = {
        key: value
        for key, value in (attributes or {}).items()
        if key.startswith("rag.") and isinstance(value, str | int | float | bool)
    }
    with tracer().start_as_current_span(name, attributes=safe):
        yield


def extract_context(headers: dict[str, str]):
    return propagate.extract(headers)


def inject_context(headers: dict[str, str]) -> None:
    propagate.inject(headers)


def attach_context(headers: dict[str, str]):
    return context.attach(extract_context(headers))


def detach_context(token: object) -> None:
    context.detach(token)  # type: ignore[arg-type]


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_http(route: str, method: str, status: int, seconds: float) -> None:
    labels = (route_label(route), bounded(method, METHODS, "OTHER"))
    HTTP_ACTIVE.labels(*labels).dec()
    HTTP_REQUESTS.labels(
        *labels, bounded(f"{status // 100}xx", STATUS_CLASSES, "5xx")
    ).inc()
    HTTP_DURATION.labels(*labels).observe(seconds)


def begin_http(route: str, method: str) -> tuple[str, str, float]:
    labels = (route_label(route), bounded(method, METHODS, "OTHER"))
    HTTP_ACTIVE.labels(*labels).inc()
    return labels[0], labels[1], perf_counter()
