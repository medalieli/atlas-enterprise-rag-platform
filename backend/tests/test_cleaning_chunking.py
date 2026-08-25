from app.ingestion.chunking import (
    ChunkingConfig,
    chunk_source_unit,
    pipeline_fingerprint,
)
from app.ingestion.cleaning import clean_source_unit, clean_text
from app.ingestion.types import SourceBlock, SourceLocation, SourceUnit


def test_cleaning_is_deterministic_and_conservative() -> None:
    raw = "Café\r\nlegal  wording\x00\r\n\r\n\r\ninter-\nnational  law"
    expected = "Café\nlegal wording\n\ninternational law"
    assert clean_text(raw) == expected
    assert clean_text(raw) == clean_text(raw)
    assert clean_text("state-\nOwned") == "state-\nOwned"


def test_chunk_offsets_hashes_bounds_and_overlap_are_reproducible() -> None:
    text = " ".join(f"Sentence {index}." for index in range(80))
    source = SourceUnit(
        0, SourceLocation("pdf", page_number=1), (SourceBlock(0, "page", text),)
    )
    cleaned = clean_source_unit(source)
    config = ChunkingConfig(180, 240, 30)
    first = chunk_source_unit(cleaned, config)
    second = chunk_source_unit(cleaned, config)
    assert first == second
    assert all(len(chunk.content) <= 240 for chunk in first)
    assert all(
        cleaned.normalized_text[chunk.start_offset : chunk.end_offset] == chunk.content
        for chunk in first
    )
    assert all(
        chunk.start_offset < previous.end_offset
        for previous, chunk in zip(first, first[1:], strict=False)
    )
    assert pipeline_fingerprint("parser-v1", config) == pipeline_fingerprint(
        "parser-v1", config
    )


def test_empty_blocks_produce_no_chunks() -> None:
    source = SourceUnit(
        0, SourceLocation("docx"), (SourceBlock(0, "paragraph", " \n "),)
    )
    cleaned = clean_source_unit(source)
    assert chunk_source_unit(cleaned, ChunkingConfig(100, 120, 10)) == ()


def test_repeated_headers_are_retained_without_a_removal_threshold() -> None:
    first = clean_text("Confidential\nPage one")
    second = clean_text("Confidential\nPage two")
    assert first.startswith("Confidential")
    assert second.startswith("Confidential")
