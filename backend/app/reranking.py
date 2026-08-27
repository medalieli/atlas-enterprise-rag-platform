import asyncio
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings
from app.retrieval import HybridCandidate


class RerankerError(Exception):
    """Safe reranker error for the API boundary."""


class RerankerUnavailableError(RerankerError):
    pass


class InvalidRerankerOutputError(RerankerError):
    pass


@dataclass(frozen=True)
class RerankInput:
    candidate_id: UUID
    passage: str


@dataclass(frozen=True)
class RerankScore:
    candidate_id: UUID
    score: float


@dataclass(frozen=True)
class RerankedCandidate:
    hybrid: HybridCandidate
    original_hybrid_rank: int
    reranker_score: float


class RerankerProvider(Protocol):
    def score(
        self, query: str, candidates: Sequence[RerankInput]
    ) -> list[RerankScore]: ...


def passage_for_reranking(candidate: HybridCandidate) -> str:
    source = candidate.candidate
    context = f"Section: {source.section_path}\n\n" if source.section_path else ""
    return f"{context}{source.content}"


class LocalCrossEncoderReranker:
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import CrossEncoder

        self.batch_size = settings.reranker_batch_size
        self.model = CrossEncoder(
            settings.reranker_model_path,
            max_length=settings.reranker_max_length,
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={"use_safetensors": True},
            processor_kwargs={"use_fast": True},
        )

    def score(self, query: str, candidates: Sequence[RerankInput]) -> list[RerankScore]:
        pairs = [(query, candidate.passage) for candidate in candidates]
        values = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        flattened = values.reshape(-1).tolist()
        return [
            RerankScore(candidate.candidate_id, float(score))
            for candidate, score in zip(candidates, flattened, strict=False)
        ]


class DeterministicFakeReranker:
    """Explicit test-only provider for isolated authentication smoke tests."""

    def score(self, query: str, candidates: Sequence[RerankInput]) -> list[RerankScore]:
        return [RerankScore(candidate.candidate_id, 0.0) for candidate in candidates]


@lru_cache
def get_reranker_provider() -> RerankerProvider:
    settings = get_settings()
    if settings.reranker_provider == "fake":
        return DeterministicFakeReranker()
    return LocalCrossEncoderReranker(settings)


@lru_cache
def _executor() -> ThreadPoolExecutor:
    settings = get_settings()
    return ThreadPoolExecutor(
        max_workers=settings.reranker_max_concurrency,
        thread_name_prefix="reranker",
    )


def validate_scores(
    candidates: Sequence[RerankInput], scores: Sequence[RerankScore]
) -> dict[UUID, float]:
    expected = [candidate.candidate_id for candidate in candidates]
    received = [score.candidate_id for score in scores]
    if len(scores) != len(candidates) or len(set(received)) != len(received):
        raise InvalidRerankerOutputError("Reranker returned an invalid score count")
    if set(received) != set(expected):
        raise InvalidRerankerOutputError("Reranker returned unknown candidate IDs")
    if not all(math.isfinite(score.score) for score in scores):
        raise InvalidRerankerOutputError("Reranker returned non-finite scores")
    return {score.candidate_id: float(score.score) for score in scores}


async def rerank_hybrid_candidates(
    query: str,
    candidates: list[HybridCandidate],
    top_k: int,
    provider: RerankerProvider,
    timeout_seconds: float,
) -> list[RerankedCandidate]:
    if not candidates:
        return []
    inputs = [
        RerankInput(candidate.candidate.chunk_id, passage_for_reranking(candidate))
        for candidate in candidates
    ]
    loop = asyncio.get_running_loop()
    try:
        raw_scores = await asyncio.wait_for(
            loop.run_in_executor(_executor(), provider.score, query, inputs),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise RerankerUnavailableError("Reranker timed out") from exc
    except RerankerError:
        raise
    except Exception as exc:
        raise RerankerUnavailableError("Reranker unavailable") from exc
    scores = validate_scores(inputs, raw_scores)
    ranked = [
        RerankedCandidate(
            candidate,
            original_rank,
            scores[candidate.candidate.chunk_id],
        )
        for original_rank, candidate in enumerate(candidates, 1)
    ]
    ranked.sort(
        key=lambda item: (
            -item.reranker_score,
            item.original_hybrid_rank,
            str(item.hybrid.candidate.chunk_id),
        )
    )
    return ranked[:top_k]


async def warm_reranker() -> None:
    provider = get_reranker_provider()
    synthetic_id = UUID(int=0)
    inputs = [RerankInput(synthetic_id, "Synthetic startup validation passage.")]
    loop = asyncio.get_running_loop()
    try:
        raw_scores = await asyncio.wait_for(
            loop.run_in_executor(
                _executor(), provider.score, "startup validation", inputs
            ),
            timeout=get_settings().reranker_timeout_seconds,
        )
        validate_scores(inputs, raw_scores)
    except Exception as exc:
        raise RuntimeError("Reranker startup validation failed") from exc
