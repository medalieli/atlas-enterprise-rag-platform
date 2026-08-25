from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.embeddings import (
    EMBEDDING_INPUT_VERSION,
    OpenAIEmbeddingProvider,
    PermanentEmbeddingError,
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
