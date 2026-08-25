import io
import zipfile
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from app.storage import (
    LocalDocumentStorage,
    UploadValidationError,
    validate_stored_file,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        io.BytesIO(content),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


def docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<w:document />")
    return output.getvalue()


@pytest.mark.asyncio
async def test_streams_pdf_and_calculates_checksum(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(str(tmp_path))
    stored = await storage.store(
        upload("guide.pdf", b"%PDF-1.7\nminimal", "application/pdf"),
        "tenant/document/original.pdf",
        100,
    )
    validate_stored_file(
        storage.path_for_validation(stored.key), ".pdf", "application/pdf", 1000
    )
    assert stored.size_bytes == 16
    assert len(stored.checksum_sha256) == 64
    assert await storage.verify(stored.key, stored.checksum_sha256)


@pytest.mark.asyncio
async def test_valid_docx_and_corrupt_docx(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(str(tmp_path))
    good = await storage.store(
        upload("guide.docx", docx_bytes(), DOCX_MIME), "good.docx", 10_000
    )
    validate_stored_file(
        storage.path_for_validation(good.key), ".docx", DOCX_MIME, 10_000
    )
    bad = await storage.store(
        upload("bad.docx", b"PK not a zip", DOCX_MIME), "bad.docx", 10_000
    )
    with pytest.raises(UploadValidationError):
        validate_stored_file(
            storage.path_for_validation(bad.key), ".docx", DOCX_MIME, 10_000
        )


@pytest.mark.asyncio
async def test_empty_oversize_and_path_traversal_are_rejected(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(str(tmp_path))
    with pytest.raises(UploadValidationError) as empty:
        await storage.store(upload("x.pdf", b"", "application/pdf"), "empty.pdf", 10)
    assert empty.value.status_code == 400
    with pytest.raises(UploadValidationError) as large:
        await storage.store(
            upload("x.pdf", b"%PDF-more-than-limit", "application/pdf"),
            "large.pdf",
            5,
        )
    assert large.value.status_code == 413
    assert not (tmp_path / "large.pdf").exists()
    with pytest.raises(ValueError):
        storage.path_for_validation("../escape.pdf")


def test_mime_extension_signature_mismatches_are_rejected(tmp_path: Path) -> None:
    disguised = tmp_path / "disguised.pdf"
    disguised.write_bytes(b"MZ executable")
    with pytest.raises(UploadValidationError):
        validate_stored_file(disguised, ".pdf", "application/pdf", 1000)
    with pytest.raises(UploadValidationError):
        validate_stored_file(disguised, ".exe", "application/pdf", 1000)
    with pytest.raises(UploadValidationError):
        validate_stored_file(disguised, ".pdf", "text/plain", 1000)
