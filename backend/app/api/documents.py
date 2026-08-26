from pathlib import PurePath
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import TrustedPrincipal, get_trusted_principal
from app.core.config import get_settings
from app.db.models import Collection, Document, Membership, ProcessingJob
from app.db.session import get_session
from app.metadata import MAX_METADATA_JSON_BYTES, DocumentMetadataInput
from app.storage import (
    LocalDocumentStorage,
    UploadValidationError,
    storage_key,
    validate_stored_file,
)
from app.tasks import verify_original_task

router = APIRouter(tags=["documents"])


class UploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID
    original_filename: str
    processing_status: str


class JobResponse(BaseModel):
    job_id: UUID
    document_id: UUID
    status: str
    attempt_count: int
    error_message: str | None


@router.post(
    "/collections/{collection_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResponse,
)
async def upload_document(
    collection_id: UUID,
    file: Annotated[UploadFile, File()],
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    metadata: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    collection = await session.scalar(
        select(Collection)
        .join(
            Membership,
            (Membership.tenant_id == Collection.tenant_id)
            & (Membership.user_id == principal.user_id),
        )
        .where(
            Collection.id == collection_id,
            Collection.tenant_id == principal.tenant_id,
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        if metadata is None:
            document_metadata = DocumentMetadataInput()
        else:
            if len(metadata.encode()) > MAX_METADATA_JSON_BYTES:
                raise ValueError("metadata is too large")
            document_metadata = DocumentMetadataInput.model_validate_json(metadata)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Document metadata is invalid"
        ) from exc

    filename = PurePath(file.filename or "").name[:512]
    extension = PurePath(filename).suffix.lower()
    settings = get_settings()
    document_id, job_id = uuid4(), uuid4()
    key = storage_key(principal.tenant_id, document_id, extension)
    storage = LocalDocumentStorage(settings.document_storage_path)
    try:
        stored = await storage.store(file, key, settings.max_upload_bytes)
        validate_stored_file(
            storage.path_for_validation(key),
            extension,
            file.content_type or "",
            settings.max_docx_uncompressed_bytes,
        )
        document = Document(
            id=document_id,
            tenant_id=principal.tenant_id,
            collection_id=collection_id,
            filename=filename,
            storage_key=key,
            content_type=file.content_type or "",
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            document_metadata=document_metadata.to_storage(),
        )
        job = ProcessingJob(
            id=job_id,
            tenant_id=principal.tenant_id,
            document_id=document_id,
            operation="verify_original",
        )
        session.add_all([document, job])
        await session.commit()
    except UploadValidationError as exc:
        await storage.delete(key)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        await session.rollback()
        await storage.delete(key)
        raise HTTPException(
            status_code=503, detail="Upload could not be stored"
        ) from exc

    try:
        verify_original_task.apply_async(
            args=[str(principal.tenant_id), str(document_id), str(job_id)]
        )
    except Exception as exc:
        await session.execute(delete(ProcessingJob).where(ProcessingJob.id == job_id))
        await session.execute(delete(Document).where(Document.id == document_id))
        await session.commit()
        await storage.delete(key)
        raise HTTPException(
            status_code=503, detail="Document queue is unavailable"
        ) from exc

    return UploadResponse(
        document_id=document_id,
        job_id=job_id,
        original_filename=filename,
        processing_status="queued",
    )


@router.get("/processing-jobs/{job_id}", response_model=JobResponse)
async def get_processing_job(
    job_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobResponse:
    job = await session.scalar(
        select(ProcessingJob)
        .join(
            Membership,
            (Membership.tenant_id == ProcessingJob.tenant_id)
            & (Membership.user_id == principal.user_id),
        )
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.tenant_id == principal.tenant_id,
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return JobResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
    )
