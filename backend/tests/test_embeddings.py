from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.core.config import Settings
from app.embeddings import (
    EMBEDDING_INPUT_VERSION,
    PERMANENT_QUOTA_CODES,
    OpenAIEmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
    build_embedding_input,
    embedding_fingerprint,
    token_batches,
    validate_vector,
)


def test_embedding_input_and_fingerprint_are_deterministic() -> None:
    assert build_embedding_input("Exact content", "Policy / Refunds") == (
        "Section: Policy / Refunds\n\nExact content"
    )
    first = embedding_fingerprint("a" * 64, "model-a", 1536)
    assert first == embedding_fingerprint("a" * 64, "model-a", 1536)
    assert first != embedding_fingerprint("a" * 64, "model-b", 1536)
    assert EMBEDDING_INPUT_VERSION == "embedding-input-v1"


@pytest.mark.parametrize(
    "vector",
    ([1.0], [float("nan")] * 1536, [float("inf")] * 1536, [0.0] * 1536),
)
def test_vector_validation_rejects_invalid_vectors(vector: list[float]) -> None:
    with pytest.raises(PermanentEmbeddingError):
        validate_vector(vector, 1536)


def test_token_aware_batches_preserve_input_order() -> None:
    settings = Settings(embedding_batch_size=2, embedding_max_batch_tokens=20)
    texts = ["one", "two", "three"]
    batches = token_batches(texts, settings)
    assert [text for batch in batches for text in batch.texts] == texts
    assert [len(batch.texts) for batch in batches] == [2, 1]


@pytest.mark.asyncio
async def test_openai_response_indexes_restore_order_and_validate_count() -> None:
    class Embeddings:
        async def create(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[2.0] * 1536),
                    SimpleNamespace(index=0, embedding=[1.0] * 1536),
                ]
            )

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    vectors = await provider.embed_documents(["first", "second"])
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


@pytest.mark.asyncio
async def test_incorrect_response_count_is_permanent() -> None:
    class Embeddings:
        async def create(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(data=[])

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    with pytest.raises(PermanentEmbeddingError):
        await provider.embed_documents(["first"])


def rate_limit_error(
    code: str | None, error_type: str, *, retry_after: str | None = None
) -> RateLimitError:
    headers = {"x-request-id": "req_safe_synthetic"}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://api.openai.com/v1/embeddings"),
    )
    return RateLimitError(
        "synthetic provider error",
        response=response,
        body={"error": {"code": code, "type": error_type}},
    )


@pytest.mark.parametrize("code", sorted(PERMANENT_QUOTA_CODES))
@pytest.mark.asyncio
async def test_quota_rate_limit_codes_are_permanent(code: str) -> None:
    class Embeddings:
        async def create(self, **_: object) -> object:
            raise rate_limit_error(code, "tokens")

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    with pytest.raises(PermanentEmbeddingError) as captured:
        await provider.embed_documents(["synthetic input"])
    assert captured.value.metadata is not None
    assert captured.value.metadata.code == code
    assert captured.value.metadata.retryable is False


@pytest.mark.asyncio
async def test_insufficient_quota_type_is_permanent_without_code() -> None:
    class Embeddings:
        async def create(self, **_: object) -> object:
            raise rate_limit_error(None, "insufficient_quota")

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    with pytest.raises(PermanentEmbeddingError) as captured:
        await provider.embed_documents(["synthetic input"])
    assert captured.value.metadata is not None
    assert captured.value.metadata.retryable is False


@pytest.mark.asyncio
async def test_unrecognized_rate_limit_is_non_retryable() -> None:
    class Embeddings:
        async def create(self, **_: object) -> object:
            raise rate_limit_error(None, "unknown")

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    with pytest.raises(PermanentEmbeddingError) as captured:
        await provider.embed_documents(["synthetic input"])
    assert captured.value.metadata is not None
    assert captured.value.metadata.retryable is False


@pytest.mark.asyncio
async def test_temporary_rate_limit_is_retryable_and_preserves_safe_metadata() -> None:
    class Embeddings:
        async def create(self, **_: object) -> object:
            raise rate_limit_error("rate_limit_exceeded", "requests", retry_after="7")

    provider = object.__new__(OpenAIEmbeddingProvider)
    provider.settings = Settings(openai_api_key="synthetic-test-key")
    provider.client = SimpleNamespace(embeddings=Embeddings())
    with pytest.raises(TransientEmbeddingError) as captured:
        await provider.embed_documents(["synthetic input"])
    metadata = captured.value.metadata
    assert metadata is not None
    assert metadata.retryable is True
    assert metadata.retry_after_seconds == 7
    assert metadata.request_id == "req_safe_synthetic"
