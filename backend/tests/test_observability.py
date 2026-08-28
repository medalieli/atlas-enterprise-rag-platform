import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient
from opentelemetry import propagate

from app.core.config import get_settings
from app.main import app
from app.observability import (
    ERROR_CATEGORIES,
    METHODS,
    RETRIEVAL_MODES,
    SAFE_ROUTES,
    SPAN_NAMES,
    SafeJsonFormatter,
    bounded,
    configured_model_label,
    route_label,
    stage,
)
from app.worker import inject_trace


def test_metric_dimensions_are_explicit_and_bounded() -> None:
    assert bounded("GET", METHODS, "OTHER") == "GET"
    assert bounded(str(uuid4()), METHODS, "OTHER") == "OTHER"
    assert "semantic" in RETRIEVAL_MODES
    assert "internal" in ERROR_CATEGORIES
    assert all("{" not in label or label in SAFE_ROUTES for label in SAFE_ROUTES)
    assert configured_model_label("configured", "configured") == "configured"
    assert configured_model_label(str(uuid4()), "configured") == "other"


def test_route_templates_never_emit_identifiers() -> None:
    identifier = str(uuid4())
    assert (
        route_label(f"/collections/{identifier}/documents")
        == "/collections/{collection_id}/documents"
    )
    assert identifier not in route_label(f"/collections/{identifier}/documents")
    assert route_label(f"/unknown/{identifier}") == "unmatched"


def test_span_names_and_attributes_are_registered_and_safe() -> None:
    assert "http.server.request" in SPAN_NAMES
    with stage("ingestion.parse", {"rag.operation": "ingestion", "rag.unit_count": 2}):
        pass
    try:
        with stage("dynamic-span-name"):
            pass
    except ValueError as exc:
        assert "not registered" in str(exc)
    else:
        raise AssertionError("dynamic span name was accepted")


def test_structured_log_correlation_redacts_credentials() -> None:
    record = logging.LogRecord(
        "rag",
        logging.INFO,
        __file__,
        1,
        "Authorization: Bearer token-value access_token=secret-value",
        (),
        None,
    )
    payload = json.loads(SafeJsonFormatter().format(record))
    assert payload["message"].count("[REDACTED]") >= 1
    assert "token-value" not in payload["message"]
    assert set(payload) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "request_id",
        "trace_id",
        "span_id",
    }


def test_celery_publish_injects_w3c_context_without_business_identifiers() -> None:
    headers: dict[str, object] = {}
    inject_trace(headers=headers)
    assert set(headers) <= {"traceparent", "tracestate", "baggage"}
    propagate.extract(headers)  # must accept the emitted carrier


def test_metrics_endpoint_is_hidden_without_configuration(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_enabled", False)
    response = TestClient(app).get("/internal/metrics")
    assert response.status_code == 404
    assert "secret" not in response.text.lower()
