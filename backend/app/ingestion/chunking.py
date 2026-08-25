import hashlib
import json
import re
from dataclasses import dataclass

from app.ingestion.cleaning import CLEANER_VERSION
from app.ingestion.types import ChunkCandidate, CleanedSourceUnit

CHUNKER_VERSION = "chunk-v1"
_SENTENCE_END = re.compile(r"[.!?](?:[\"')\]]*)\s+")


@dataclass(frozen=True)
class ChunkingConfig:
    target_chars: int
    max_chars: int
    overlap_chars: int

    def __post_init__(self) -> None:
        if not 1 <= self.target_chars <= self.max_chars:
            raise ValueError("target_chars must be between 1 and max_chars")
        if not 0 <= self.overlap_chars < self.target_chars:
            raise ValueError("overlap_chars must be smaller than target_chars")


def pipeline_fingerprint(parser_version: str, config: ChunkingConfig) -> str:
    payload = json.dumps(
        {
            "parser": parser_version,
            "cleaner": CLEANER_VERSION,
            "chunker": CHUNKER_VERSION,
            "target": config.target_chars,
            "maximum": config.max_chars,
            "overlap": config.overlap_chars,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _preferred_end(text: str, start: int, config: ChunkingConfig) -> int:
    hard_end = min(len(text), start + config.max_chars)
    if hard_end == len(text):
        return hard_end
    target_end = min(hard_end, start + config.target_chars)
    candidates = [
        match.end() for match in _SENTENCE_END.finditer(text, start, hard_end)
    ]
    after = [position for position in candidates if position >= target_end]
    if after:
        return after[0]
    before = [position for position in candidates if position > start]
    if before:
        return before[-1]
    whitespace = text.rfind(" ", start + 1, hard_end + 1)
    return whitespace if whitespace > start else hard_end


def chunk_source_unit(
    unit: CleanedSourceUnit, config: ChunkingConfig
) -> tuple[ChunkCandidate, ...]:
    text = unit.normalized_text
    if not text:
        return ()
    chunks: list[ChunkCandidate] = []
    start = 0
    while start < len(text):
        end = _preferred_end(text, start, config)
        content = text[start:end]
        if content:
            chunks.append(
                ChunkCandidate(
                    source_unit_index=unit.unit_index,
                    content=content,
                    start_offset=start,
                    end_offset=end,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                )
            )
        if end >= len(text):
            break
        next_start = max(start + 1, end - config.overlap_chars)
        boundary = text.find(" ", next_start, end)
        start = boundary + 1 if boundary >= 0 else next_start
    return tuple(chunks)
