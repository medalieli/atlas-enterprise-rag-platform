from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceLocation:
    source_type: str
    page_number: int | None = None
    section_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceBlock:
    block_index: int
    kind: str
    text: str


@dataclass(frozen=True)
class SourceUnit:
    unit_index: int
    location: SourceLocation
    blocks: tuple[SourceBlock, ...]


@dataclass(frozen=True)
class ParsedDocument:
    parser_version: str
    source_units: tuple[SourceUnit, ...]


@dataclass(frozen=True)
class CleanedSourceUnit:
    unit_index: int
    location: SourceLocation
    normalized_text: str
    block_boundaries: tuple[dict[str, int | str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ChunkCandidate:
    source_unit_index: int
    content: str
    start_offset: int
    end_offset: int
    content_hash: str
