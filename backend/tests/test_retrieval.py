from uuid import UUID

import pytest

from app.retrieval import (
    MAX_CANDIDATES_PER_BRANCH,
    RRF_K,
    RetrievalCandidate,
    candidate_depth,
    extract_query_identifiers,
    inject_identifier_candidates,
    reciprocal_rank_fusion,
)


def candidate(number: int, score: float = 1.0) -> RetrievalCandidate:
    chunk_id = UUID(int=number)
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id=UUID(int=number + 100),
        document_name=f"synthetic-{number}.pdf",
        content=f"synthetic content {number}",
        page_number=number,
        section_path=None,
        start_offset=0,
        end_offset=10,
        score=score,
    )


def test_rrf_deduplicates_and_both_channels_rank_above_single_channel() -> None:
    both = candidate(1, 0.9)
    semantic_only = candidate(2, 0.8)
    keyword_only = candidate(3, 0.7)
    results = reciprocal_rank_fusion(
        [both, semantic_only], [both, keyword_only], top_k=10
    )

    assert [item.candidate.chunk_id for item in results] == [
        both.chunk_id,
        semantic_only.chunk_id,
        keyword_only.chunk_id,
    ]
    assert results[0].hybrid_score == pytest.approx(2 / (RRF_K + 1))
    assert results[0].semantic_rank == 1
    assert results[0].keyword_rank == 1
    assert len({item.candidate.chunk_id for item in results}) == 3


def test_rrf_is_deterministic_for_ties_and_empty_lists() -> None:
    higher_id = candidate(20)
    lower_id = candidate(10)
    results = reciprocal_rank_fusion([higher_id], [lower_id], top_k=10)
    assert [item.candidate.chunk_id for item in results] == [
        lower_id.chunk_id,
        higher_id.chunk_id,
    ]
    assert reciprocal_rank_fusion([], [], top_k=10) == []


def test_rrf_top_k_and_candidate_depth_are_bounded() -> None:
    semantic = [candidate(number) for number in range(1, 101)]
    assert len(reciprocal_rank_fusion(semantic, [], top_k=5)) == 5
    assert candidate_depth(1) == 4
    assert candidate_depth(50) == MAX_CANDIDATES_PER_BRANCH == 200


def test_identifier_extraction_is_ordered_case_insensitive_and_bounded() -> None:
    query = "Compare sec-028 with FINORION1028 and SEC-028, not loose FIN-28."
    assert extract_query_identifiers(query) == ("SEC-028", "FINORION1028")


def test_identifier_candidates_are_injected_without_duplicates() -> None:
    exact = candidate(9)
    fused = reciprocal_rank_fusion([candidate(1), exact], [], top_k=10)
    results = inject_identifier_candidates(fused, [exact], 10)
    assert results[0].candidate.chunk_id == exact.chunk_id
    assert [item.candidate.chunk_id for item in results].count(exact.chunk_id) == 1
