from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.ingestion.parsers import (
    OcrRequiredError,
    ParserLimitError,
    ParserLimits,
    PermanentParserError,
    parse_docx,
    parse_pdf,
)
from tests.fixture_builders import docx_bytes, pdf_bytes

LIMITS = ParserLimits(10, 10_000, 100_000, 10)


def test_pdf_preserves_one_based_pages(tmp_path: Path) -> None:
    path = tmp_path / "pages.pdf"
    path.write_bytes(pdf_bytes(["Page one text.", "Page two text."]))
    parsed = parse_pdf(path, LIMITS)
    assert parsed == parse_pdf(path, LIMITS)
    assert [unit.location.page_number for unit in parsed.source_units] == [1, 2]
    assert "Page one" in parsed.source_units[0].blocks[0].text
    assert "Page two" in parsed.source_units[1].blocks[0].text


def test_docx_preserves_headings_lists_tables_and_order(tmp_path: Path) -> None:
    path = tmp_path / "structured.docx"
    path.write_bytes(docx_bytes())
    parsed = parse_docx(path, LIMITS)
    assert parsed == parse_docx(path, LIMITS)
    assert parsed.source_units[0].location.section_path == ("Policy",)
    assert parsed.source_units[1].location.section_path == ("Policy", "Details")
    kinds = [block.kind for unit in parsed.source_units for block in unit.blocks]
    assert kinds == ["heading", "paragraph", "list", "table", "heading", "paragraph"]
    assert "A | B\n1 | 2" in parsed.source_units[0].blocks[-1].text


def test_corrupt_and_image_only_pdf_fail_safely(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-not-valid")
    with pytest.raises(PermanentParserError):
        parse_pdf(corrupt, LIMITS)
    image_only = tmp_path / "image-only.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with image_only.open("wb") as output:
        writer.write(output)
    with pytest.raises(OcrRequiredError):
        parse_pdf(image_only, LIMITS)


def test_encrypted_pdf_and_corrupt_docx_fail_safely(tmp_path: Path) -> None:
    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("test-only-password")
    with encrypted.open("wb") as output:
        writer.write(output)
    with pytest.raises(PermanentParserError, match="Encrypted"):
        parse_pdf(encrypted, LIMITS)
    corrupt_docx = tmp_path / "corrupt.docx"
    corrupt_docx.write_bytes(b"PK malformed")
    with pytest.raises(PermanentParserError):
        parse_docx(corrupt_docx, LIMITS)


def test_pdf_page_and_character_limits(tmp_path: Path) -> None:
    path = tmp_path / "limited.pdf"
    path.write_bytes(pdf_bytes(["first", "second"]))
    with pytest.raises(ParserLimitError):
        parse_pdf(path, ParserLimits(1, 100, 100_000, 10))
    with pytest.raises(ParserLimitError):
        parse_pdf(path, ParserLimits(10, 3, 100_000, 10))
    with pytest.raises(ParserLimitError):
        parse_pdf(path, ParserLimits(10, 100, 1, 10))
