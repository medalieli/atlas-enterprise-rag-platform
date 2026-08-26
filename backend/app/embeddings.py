import hashlib
import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import tiktoken
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

from app.core.config import Settings

EMBEDDING_INPUT_VERSION = "embedding-input-v1"
logger = logging.getLogger(__name__)

PERMANENT_QUOTA_CODES = frozenset(
    {
        "credit_balance_exhausted",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
        "insufficient_quota",
    }
)
TEMPORARY_RATE_LIMIT_CODES = frozenset({"rate_limit_exceeded"})
TEMPORARY_RATE_LIMIT_TYPES = frozenset(
    {
        "rate_limit_exceeded",
        "requests",
        "requests_per_minute",
        "tokens",
        "tokens_per_minute",
    }
)


@dataclass(frozen=True)
class ProviderErrorMetadata:
    http_status: int | None
    code: str | None
    error_type: str | None
    retryable: bool
    retry_after_seconds: float | None = None
    request_id: str | None = None


class EmbeddingError(Exception):
    """Base error safe for orchestration boundaries."""

    def __init__(
        self, message: str, metadata: ProviderErrorMetadata | None = None
    ) -> None:
        super().__init__(message)
        self.metadata = metadata


class TransientEmbeddingError(EmbeddingError):
    pass


class PermanentEmbeddingError(EmbeddingError):
    pass


class EmbeddingConfigurationError(PermanentEmbeddingError):
    pass


def _normalized_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
        return seconds if seconds >= 0 else None
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def normalize_rate_limit_error(exc: RateLimitError) -> ProviderErrorMetadata:
    body = exc.body if isinstance(exc.body, dict) else {}
    nested = body.get("error")
    error = nested if isinstance(nested, dict) else body
    code = _normalized_string(error.get("code"))
    error_type = _normalized_string(error.get("type"))
    # OpenAI may use insufficient_quota as either the code or the type.
    permanent = code in PERMANENT_QUOTA_CODES or error_type in PERMANENT_QUOTA_CODES
    temporary = (
        code in TEMPORARY_RATE_LIMIT_CODES or error_type in TEMPORARY_RATE_LIMIT_TYPES
    )
    headers = exc.response.headers
    return ProviderErrorMetadata(
        http_status=exc.status_code,
        code=code,
        error_type=error_type,
        retryable=temporary and not permanent,
        retry_after_seconds=_retry_after_seconds(headers.get("retry-after")),
        request_id=headers.get("x-request-id"),
    )


def _log_provider_error(metadata: ProviderErrorMetadata) -> None:
    logger.warning(
        "Embedding provider request failed status=%s code=%s type=%s "
        "retryable=%s retry_after_present=%s request_id=%s",
        metadata.http_status,
        metadata.code,
        metadata.error_type,
        metadata.retryable,
        metadata.retry_after_seconds is not None,
        metadata.request_id,
    )


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def build_embedding_input(content: str, section: str | None) -> str:
    if not content:
        raise PermanentEmbeddingError("Embedding input content is empty")
    context = f"Section: {section}\n\n" if section else ""
    return f"{context}{content}"


def embedding_fingerprint(
    embedding_input_hash: str, model: str, dimensions: int
) -> str:
    payload = {
        "embedding_input_hash": embedding_input_hash,
        "dimensions": dimensions,
        "input_version": EMBEDDING_INPUT_VERSION,
        "model": model,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_vector(vector: Sequence[float], dimensions: int) -> list[float]:
    values = [float(value) for value in vector]
    if len(values) != dimensions:
        raise PermanentEmbeddingError("Embedding dimension mismatch")
    if not all(math.isfinite(value) for value in values):
        raise PermanentEmbeddingError("Embedding contains non-finite values")
    if not any(value != 0 for value in values):
        raise PermanentEmbeddingError("Embedding is an all-zero vector")
    return values


@dataclass(frozen=True)
class EmbeddingBatch:
    texts: tuple[str, ...]


def token_batches(texts: Sequence[str], settings: Settings) -> list[EmbeddingBatch]:
    encoding = tiktoken.encoding_for_model(settings.embedding_model)
    result: list[EmbeddingBatch] = []
    batch: list[str] = []
    tokens = 0
    for text in texts:
        count = len(encoding.encode(text))
        if count == 0 or count > settings.embedding_max_input_tokens:
            raise PermanentEmbeddingError("Embedding input token limit exceeded")
        if batch and (
            len(batch) >= settings.embedding_batch_size
            or tokens + count > settings.embedding_max_batch_tokens
        ):
            result.append(EmbeddingBatch(tuple(batch)))
            batch, tokens = [], 0
        batch.append(text)
        tokens += count
    if batch:
        result.append(EmbeddingBatch(tuple(batch)))
    return result


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise EmbeddingConfigurationError("OPENAI_API_KEY is not configured")
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.embedding_request_timeout_seconds,
            max_retries=settings.embedding_provider_max_retries,
        )

    async def _request(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self.client.embeddings.create(
                input=list(texts),
                model=self.settings.embedding_model,
                dimensions=self.settings.embedding_dimensions,
                encoding_format="float",
            )
        except RateLimitError as exc:
            metadata = normalize_rate_limit_error(exc)
            _log_provider_error(metadata)
            error_type = (
                TransientEmbeddingError
                if metadata.retryable
                else PermanentEmbeddingError
            )
            raise error_type(
                "Embedding provider rate limit or quota error", metadata
            ) from exc
        except (APITimeoutError, APIConnectionError, InternalServerError) as exc:
            raise TransientEmbeddingError(
                "Embedding provider temporarily unavailable"
            ) from exc
        except (AuthenticationError, PermissionDeniedError, BadRequestError) as exc:
            raise PermanentEmbeddingError(
                "Embedding provider rejected the request"
            ) from exc
        data = sorted(response.data, key=lambda item: item.index)
        indexes = [item.index for item in data]
        if indexes != list(range(len(texts))) or len(data) != len(texts):
            raise PermanentEmbeddingError("Embedding response indexes are invalid")
        return [
            validate_vector(item.embedding, self.settings.embedding_dimensions)
            for item in data
        ]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in token_batches(texts, self.settings):
            vectors.extend(await self._request(batch.texts))
        if len(vectors) != len(texts):
            raise PermanentEmbeddingError("Embedding response count mismatch")
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        batches = token_batches([text], self.settings)
        return (await self._request(batches[0].texts))[0]


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return OpenAIEmbeddingProvider(settings)
