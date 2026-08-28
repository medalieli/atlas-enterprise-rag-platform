from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun
from opentelemetry import context, propagate, trace

from app.core.config import get_settings
from app.observability import configure, tracer

settings = get_settings()
configure(settings)
celery_app = Celery("rag_ingestion", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
)
celery_app.autodiscover_tasks(["app"])

_task_context_tokens: dict[str, tuple[object, object]] = {}
_task_spans: dict[str, object] = {}


@before_task_publish.connect
def inject_trace(headers: dict[str, object] | None = None, **_: object) -> None:
    if headers is not None:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        headers.update(carrier)


@task_prerun.connect
def start_task_trace(
    task_id: str | None = None, task: object = None, **_: object
) -> None:
    if not task_id:
        return
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", {}) or {}
    parent_token = context.attach(propagate.extract(headers))
    span = tracer().start_span(
        "celery.task.execute",
        kind=trace.SpanKind.CONSUMER,
        attributes={
            "rag.operation": "ingestion"
            if getattr(task, "name", "") == "documents.verify_original"
            else "deletion"
        },
    )
    span_token = context.attach(trace.set_span_in_context(span))
    _task_context_tokens[task_id] = (parent_token, span_token)
    _task_spans[task_id] = span


@task_postrun.connect
def finish_task_trace(task_id: str | None = None, **_: object) -> None:
    if not task_id:
        return
    span = _task_spans.pop(task_id, None)
    if span is not None:
        span.end()  # type: ignore[union-attr]
    tokens = _task_context_tokens.pop(task_id, None)
    if tokens is not None:
        parent_token, span_token = tokens
        context.detach(span_token)  # type: ignore[arg-type]
        context.detach(parent_token)  # type: ignore[arg-type]
