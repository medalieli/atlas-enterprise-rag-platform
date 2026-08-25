import re
import unicodedata

from app.ingestion.types import CleanedSourceUnit, SourceUnit

CLEANER_VERSION = "clean-v1"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_DEHYPHENATE = re.compile(r"(?<=[a-z]{2})-\n(?=[a-z]{2})")


def clean_text(value: str) -> str:
    """Normalize without rewriting meaning; rules are versioned by CLEANER_VERSION."""
    value = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    value = _CONTROL.sub("", value)
    value = _DEHYPHENATE.sub("", value)
    lines = [_SPACES.sub(" ", line).strip() for line in value.split("\n")]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def clean_source_unit(unit: SourceUnit) -> CleanedSourceUnit:
    parts: list[str] = []
    boundaries: list[dict[str, int | str]] = []
    offset = 0
    for block in unit.blocks:
        cleaned = clean_text(block.text)
        if not cleaned:
            continue
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(cleaned)
        offset += len(cleaned)
        boundaries.append(
            {
                "block_index": block.block_index,
                "kind": block.kind,
                "start_offset": start,
                "end_offset": offset,
            }
        )
    return CleanedSourceUnit(
        unit_index=unit.unit_index,
        location=unit.location,
        normalized_text="".join(parts),
        block_boundaries=tuple(boundaries),
    )
