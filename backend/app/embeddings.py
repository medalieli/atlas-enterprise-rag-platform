import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
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


class EmbeddingError(Exception):
    """Base error safe for orchestration boundaries."""


class TransientEmbeddingError(EmbeddingError):
    pass


class PermanentEmbeddingError(EmbeddingError):
    pass


class EmbeddingConfigurationError(PermanentEmbeddingError):
    pass


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
        except (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            InternalServerError,
        ) as exc:
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
