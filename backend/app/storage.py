import hashlib
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID

from fastapi import UploadFile


class UploadValidationError(Exception):
    def __init__(self, detail: str, status_code: int = 415) -> None:
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class StoredUpload:
    key: str
    size_bytes: int
    checksum_sha256: str


class DocumentStorage(Protocol):
    async def store(
        self, upload: UploadFile, key: str, max_bytes: int
    ) -> StoredUpload: ...
    async def delete(self, key: str) -> None: ...
    async def verify(self, key: str, checksum: str) -> bool: ...


class LocalDocumentStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Invalid storage key")
        path = (self.root / Path(*pure.parts)).resolve()
        if self.root not in path.parents:
            raise ValueError("Invalid storage key")
        return path

    async def store(self, upload: UploadFile, key: str, max_bytes: int) -> StoredUpload:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial")
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open("xb") as output:
                while chunk := await upload.read(64 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise UploadValidationError(
                            "Upload exceeds configured size limit", 413
                        )
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size == 0:
                raise UploadValidationError("Uploaded file is empty", 400)
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return StoredUpload(key, size, digest.hexdigest())

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def verify(self, key: str, checksum: str) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
        return digest.hexdigest() == checksum

    def path_for_validation(self, key: str) -> Path:
        return self._path(key)


def validate_stored_file(
    path: Path, extension: str, content_type: str, max_uncompressed: int
) -> None:
    allowed = {
        ".pdf": "application/pdf",
        ".docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    }
    if extension not in allowed or content_type != allowed[extension]:
        raise UploadValidationError("Unsupported or mismatched document type")
    if extension == ".pdf":
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise UploadValidationError("File content is not a valid PDF")
        return
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required <= names:
                raise UploadValidationError("File content is not a valid DOCX")
            total = 0
            for info in archive.infolist():
                total += info.file_size
                if total > max_uncompressed or info.file_size > max_uncompressed:
                    raise UploadValidationError("DOCX expanded content is too large")
                if info.compress_size and info.file_size / info.compress_size > 1000:
                    raise UploadValidationError("DOCX compression ratio is unsafe")
            archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as exc:
        raise UploadValidationError("File content is not a valid DOCX") from exc


def storage_key(tenant_id: UUID, document_id: UUID, extension: str) -> str:
    return f"{tenant_id.hex}/{document_id.hex}/original{extension}"
