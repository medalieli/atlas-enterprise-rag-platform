from pathlib import PurePath
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.enterprise import business_audit_event
from app.auth import (
    CollectionPermission,
    TrustedPrincipal,
    get_trusted_principal,
    require_collection_permission,
)
from app.core.config import get_settings
from app.db.models import (
    Document,
    DocumentIndexGeneration,
    DocumentVersion,
    ProcessingJob,
)
from app.db.session import get_session
from app.lifecycle import index_configuration
from app.metadata import MAX_METADATA_JSON_BYTES, DocumentMetadataInput
from app.observability import INGESTION_QUEUE
from app.storage import (
    LocalDocumentStorage,
    UploadValidationError,
    validate_stored_file,
    version_storage_key,
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
    tenant_id, _, _ = await require_collection_permission(
        session, principal.user_id, collection_id, CollectionPermission.UPLOAD
    )

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
    document_id, version_id, generation_id, job_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    # Preserve the compatibility contract for newly-created version 1 as well.
    version_id = document_id
    key = version_storage_key(tenant_id, document_id, version_id, extension)
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
            tenant_id=tenant_id,
            collection_id=collection_id,
        )
        configuration = index_configuration(file.content_type or "", settings)
        version = DocumentVersion(
            id=version_id,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            version_number=1,
            storage_key=key,
            checksum_sha256=stored.checksum_sha256,
            filename=filename,
            content_type=file.content_type or "",
            size_bytes=stored.size_bytes,
            document_metadata=document_metadata.to_storage(),
            requested_by_user_id=principal.user_id,
        )
        generation = DocumentIndexGeneration(
            id=generation_id,
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            generation_number=1,
            requested_by_user_id=principal.user_id,
            **configuration.__dict__,
            configuration_fingerprint=configuration.fingerprint,
        )
        job = ProcessingJob(
            id=job_id,
            tenant_id=tenant_id,
            document_id=document_id,
            document_version_id=version_id,
            generation_id=generation_id,
            requested_by_user_id=principal.user_id,
            operation="initial_ingestion",
        )
        generation.processing_job_id = job_id
        session.add(document)
        await session.flush()
        session.add(version)
        await session.flush()
        session.add(generation)
        await session.flush()
        session.add(job)
        session.add(
            business_audit_event(
                tenant_id,
                principal.user_id,
                None,
                "document.uploaded",
                "document",
                document_id,
            )
        )
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
            args=[str(tenant_id), str(document_id), str(job_id)]
        )
    except Exception as exc:
        # The committed job is durable intent. Reconciliation can publish it
        # after a transient broker outage without losing the stored source.
        _ = exc

    INGESTION_QUEUE.labels("ingestion").inc()

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
    job = await session.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    document = await session.scalar(
        select(Document).where(
            Document.id == job.document_id, Document.tenant_id == job.tenant_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    await require_collection_permission(
        session, principal.user_id, document.collection_id, CollectionPermission.READ
    )
    return JobResponse(
        job_id=job.id,
        document_id=job.document_id,
        status=job.status.value,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
    )
