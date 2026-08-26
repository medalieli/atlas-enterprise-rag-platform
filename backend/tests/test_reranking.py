from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.core.config import Settings
from app.reranking import (
    InvalidRerankerOutputError,
    LocalCrossEncoderReranker,
    RerankerUnavailableError,
    RerankInput,
    RerankScore,
    get_reranker_provider,
    passage_for_reranking,
    rerank_hybrid_candidates,
)
from app.retrieval import HybridCandidate, RetrievalCandidate


def hybrid(number: int, rank: int, content: str = "exact source") -> HybridCandidate:
    return HybridCandidate(
        candidate=RetrievalCandidate(
            chunk_id=UUID(int=number),
            document_id=UUID(int=number + 100),
            document_name=f"safe-{number}.pdf",
            content=content,
            page_number=number,
            section_path="Policy",
            start_offset=0,
            end_offset=len(content),
            score=0.8,
            content_type="application/pdf",
            document_created_at=datetime(2026, 1, 1, tzinfo=UTC),
            document_metadata={"tags": ["safe"], "department": "legal"},
        ),
        hybrid_score=1 / (60 + rank),
        semantic_rank=rank,
        semantic_score=0.8,
        keyword_rank=None,
        keyword_score=None,
    )


class FakeReranker:
    def __init__(self, scores: dict[UUID, float]) -> None:
        self.scores = scores
        self.calls = 0
        self.inputs: list[RerankInput] = []

    def score(self, query: str, candidates: Sequence[RerankInput]) -> list[RerankScore]:
        self.calls += 1
        self.inputs = list(candidates)
        return [
            RerankScore(item.candidate_id, self.scores[item.candidate_id])
            for item in candidates
        ]


@pytest.mark.asyncio
async def test_fake_reranker_orders_and_preserves_original_rank_and_passage() -> None:
    first, second = hybrid(1, 1), hybrid(2, 2)
    provider = FakeReranker({UUID(int=1): 0.1, UUID(int=2): 2.0})
    result = await rerank_hybrid_candidates(
        "safe query", [first, second], 2, provider, 1
    )
    assert [item.hybrid.candidate.chunk_id for item in result] == [
        UUID(int=2),
        UUID(int=1),
    ]
    assert [item.original_hybrid_rank for item in result] == [2, 1]
    assert provider.calls == 1
    assert provider.inputs[0].passage == "Section: Policy\n\nexact source"
    assert passage_for_reranking(first).endswith(first.candidate.content)


@pytest.mark.asyncio
async def test_equal_scores_use_hybrid_rank_then_uuid_and_top_k() -> None:
    candidates = [hybrid(3, 1), hybrid(1, 2), hybrid(2, 3)]
    provider = FakeReranker({item.candidate.chunk_id: 1.0 for item in candidates})
    result = await rerank_hybrid_candidates("query", candidates, 2, provider, 1)
    assert [item.original_hybrid_rank for item in result] == [1, 2]


@pytest.mark.asyncio
async def test_empty_candidates_do_not_call_provider() -> None:
    provider = FakeReranker({})
    assert await rerank_hybrid_candidates("query", [], 5, provider, 1) == []
    assert provider.calls == 0


class BadReranker:
    def __init__(self, scores: list[RerankScore]) -> None:
        self.scores = scores

    def score(self, query: str, candidates: Sequence[RerankInput]) -> list[RerankScore]:
        return self.scores


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
async def test_non_finite_scores_are_rejected(score: float) -> None:
    with pytest.raises(InvalidRerankerOutputError):
        await rerank_hybrid_candidates(
            "query",
            [hybrid(1, 1)],
            1,
            BadReranker([RerankScore(UUID(int=1), score)]),
            1,
        )


@pytest.mark.asyncio
async def test_wrong_count_and_candidate_id_are_rejected() -> None:
    with pytest.raises(InvalidRerankerOutputError):
        await rerank_hybrid_candidates("query", [hybrid(1, 1)], 1, BadReranker([]), 1)
    with pytest.raises(InvalidRerankerOutputError):
        await rerank_hybrid_candidates(
            "query", [hybrid(1, 1)], 1, BadReranker([RerankScore(UUID(int=9), 1)]), 1
        )


class SlowReranker:
    def score(self, query: str, candidates: Sequence[RerankInput]) -> list[RerankScore]:
        import time

        time.sleep(0.05)
        return [RerankScore(item.candidate_id, 1) for item in candidates]


@pytest.mark.asyncio
async def test_timeout_is_explicit() -> None:
    with pytest.raises(RerankerUnavailableError):
        await rerank_hybrid_candidates(
            "query", [hybrid(1, 1)], 1, SlowReranker(), 0.001
        )


def test_local_provider_uses_configured_batch_size() -> None:
    class Model:
        def predict(self, pairs: object, **kwargs: object) -> object:
            assert len(pairs) == 2  # type: ignore[arg-type]
            assert kwargs["batch_size"] == 7

            class Values:
                def reshape(self, _: int) -> "Values":
                    return self

                def tolist(self) -> list[float]:
                    return [0.2, 0.4]

            return Values()

    provider = LocalCrossEncoderReranker.__new__(LocalCrossEncoderReranker)
    provider.batch_size = 7
    provider.model = Model()
    inputs = [RerankInput(UUID(int=1), "one"), RerankInput(UUID(int=2), "two")]
    assert [item.score for item in provider.score("query", inputs)] == [0.2, 0.4]


def test_provider_is_loaded_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[object] = []

    class Provider:
        def __init__(self, settings: Settings) -> None:
            created.append(settings)

    monkeypatch.setattr("app.reranking.LocalCrossEncoderReranker", Provider)
    get_reranker_provider.cache_clear()
    try:
        assert get_reranker_provider() is get_reranker_provider()
        assert len(created) == 1
    finally:
        get_reranker_provider.cache_clear()
