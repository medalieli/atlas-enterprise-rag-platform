import hashlib
import json
from datetime import datetime
from pathlib import PurePath
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.enterprise import business_audit_event
from app.auth import (
    CollectionPermission,
    Permission,
    TrustedPrincipal,
    get_trusted_principal,
    has_permission,
    require_collection_permission,
)
from app.core.config import get_settings
from app.db.models import (
    Document,
    DocumentIndexGeneration,
    DocumentStatus,
    DocumentVersion,
    ProcessingJob,
    ProcessingJobStatus,
)
from app.db.session import get_session
from app.lifecycle import index_configuration
from app.metadata import MAX_METADATA_JSON_BYTES, DocumentMetadataInput
from app.observability import INGESTION_QUEUE, LIFECYCLE, stage
from app.storage import (
    LocalDocumentStorage,
    UploadValidationError,
    validate_stored_file,
    version_storage_key,
)
from app.tasks import delete_document_task, verify_original_task

router = APIRouter(tags=["document lifecycle"])


class LifecycleAccepted(BaseModel):
    document_id: UUID
    version_id: UUID | None = None
    generation_id: UUID | None = None
    job_id: UUID
    processing_status: str


class VersionInfo(BaseModel):
    id: UUID
    version_number: int
    status: str
    active: bool
    checksum_sha256: str
    filename: str
    content_type: str
    size_bytes: int
    metadata: dict[str, object]
    active_generation_id: UUID | None
    failure_category: str | None


class DocumentInfo(BaseModel):
    id: UUID
    collection_id: UUID
    status: str
    active_version_id: UUID | None
    deleted: bool


class DocumentListItem(DocumentInfo):
    filename: str | None
    content_type: str | None
    active_version_number: int | None
    active_generation_id: UUID | None
    created_at: datetime
    updated_at: datetime


class GenerationInfo(BaseModel):
    id: UUID
    generation_number: int
    status: str
    configuration_fingerprint: str
    parser_version: str
    cleaner_version: str
    chunker_version: str
    embedding_input_version: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    text_search_configuration: str
    failure_category: str | None


async def _document_and_role(
    session: AsyncSession,
    principal: TrustedPrincipal,
    collection_id: UUID,
    document_id: UUID,
) -> tuple[Document, object]:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.collection_id == collection_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _, organization_role, collection_role = await require_collection_permission(
        session, principal.user_id, collection_id, CollectionPermission.READ
    )
    return document, organization_role if organization_role.value in {
        "owner",
        "admin",
    } else collection_role


def _metadata(raw: str | None) -> dict[str, object]:
    try:
        if raw is None:
            return DocumentMetadataInput().to_storage()
        if len(raw.encode()) > MAX_METADATA_JSON_BYTES:
            raise ValueError
        return DocumentMetadataInput.model_validate_json(raw).to_storage()
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Document metadata is invalid"
        ) from exc


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@router.post(
    "/collections/{collection_id}/documents/{document_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LifecycleAccepted,
)
async def replace_document(
    collection_id: UUID,
    document_id: UUID,
    file: Annotated[UploadFile, File()],
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
    metadata: Annotated[str | None, Form()] = None,
) -> LifecycleAccepted:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.UPLOAD):
        raise HTTPException(status_code=403, detail="Permission denied")
    if (
        document.status != DocumentStatus.AVAILABLE
        or document.active_version_id is None
    ):
        raise HTTPException(status_code=409, detail="Document has no active source")
    filename = PurePath(file.filename or "").name[:512]
    extension = PurePath(filename).suffix.lower()
    validated_metadata = _metadata(metadata)
    settings = get_settings()
    version_id, generation_id, job_id = uuid4(), uuid4(), uuid4()
    key = version_storage_key(document.tenant_id, document.id, version_id, extension)
    storage = LocalDocumentStorage(settings.document_storage_path)
    try:
        stored = await storage.store(file, key, settings.max_upload_bytes)
        validate_stored_file(
            storage.path_for_validation(key),
            extension,
            file.content_type or "",
            settings.max_docx_uncompressed_bytes,
        )
    except UploadValidationError as exc:
        await storage.delete(key)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    request_fingerprint = _fingerprint(
        {
            "checksum_sha256": stored.checksum_sha256,
            "content_type": file.content_type or "",
            "filename": filename,
            "metadata": validated_metadata,
        }
    )
    existing = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == document.tenant_id,
            ProcessingJob.document_id == document.id,
            ProcessingJob.operation == "replacement_ingestion",
            ProcessingJob.idempotency_key == idempotency_key,
        )
    )
    if existing:
        await storage.delete(key)
        if existing.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409, detail="Idempotency key payload conflict"
            )
        return LifecycleAccepted(
            document_id=document.id,
            version_id=existing.document_version_id,
            generation_id=existing.generation_id,
            job_id=existing.id,
            processing_status=existing.status.value,
        )
    duplicate = await session.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.tenant_id == document.tenant_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.checksum_sha256 == stored.checksum_sha256,
        )
    )
    if duplicate:
        await storage.delete(key)
        raise HTTPException(
            status_code=409, detail="Identical source already exists; use reindex"
        )
    try:
        locked = await session.scalar(
            select(Document).where(Document.id == document.id).with_for_update()
        )
        if (
            locked is None
            or locked.status != DocumentStatus.AVAILABLE
            or locked.active_version_id is None
        ):
            raise HTTPException(status_code=409, detail="Document has no active source")
        active_operation = await session.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.tenant_id == locked.tenant_id,
                ProcessingJob.document_id == locked.id,
                ProcessingJob.operation.in_(("replacement_ingestion", "reindex")),
                ProcessingJob.status.in_(
                    (
                        ProcessingJobStatus.QUEUED,
                        ProcessingJobStatus.RUNNING,
                        ProcessingJobStatus.RETRYING,
                    )
                ),
            )
        )
        if active_operation is not None:
            raise HTTPException(
                status_code=409, detail="Document lifecycle operation in progress"
            )
        number = locked.next_version_number
        locked.next_version_number += 1
        config = index_configuration(file.content_type or "", settings)
        version = DocumentVersion(
            id=version_id,
            tenant_id=locked.tenant_id,
            collection_id=collection_id,
            document_id=locked.id,
            version_number=number,
            storage_key=key,
            checksum_sha256=stored.checksum_sha256,
            filename=filename,
            content_type=file.content_type or "",
            size_bytes=stored.size_bytes,
            document_metadata=validated_metadata,
            requested_by_user_id=principal.user_id,
        )
        generation = DocumentIndexGeneration(
            id=generation_id,
            tenant_id=locked.tenant_id,
            document_id=locked.id,
            document_version_id=version_id,
            generation_number=1,
            requested_by_user_id=principal.user_id,
            processing_job_id=job_id,
            **config.__dict__,
            configuration_fingerprint=config.fingerprint,
        )
        job = ProcessingJob(
            id=job_id,
            tenant_id=locked.tenant_id,
            document_id=locked.id,
            document_version_id=version_id,
            generation_id=generation_id,
            requested_by_user_id=principal.user_id,
            operation="replacement_ingestion",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        session.add(version)
        await session.flush()
        session.add(generation)
        await session.flush()
        session.add(job)
        session.add(
            business_audit_event(
                locked.tenant_id,
                principal.user_id,
                None,
                "document.replacement_requested",
                "document",
                locked.id,
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await storage.delete(key)
        raise
    try:
        with stage("lifecycle.replacement.enqueue", {"rag.operation": "replacement"}):
            verify_original_task.apply_async(
                args=[str(document.tenant_id), str(document.id), str(job_id)]
            )
    except Exception:
        pass  # durable queued intent is recovered by reconciliation
    INGESTION_QUEUE.labels("replacement").inc()
    LIFECYCLE.labels("replacement", "succeeded").inc()
    return LifecycleAccepted(
        document_id=document.id,
        version_id=version_id,
        generation_id=generation_id,
        job_id=job_id,
        processing_status="queued",
    )


@router.post(
    "/collections/{collection_id}/documents/{document_id}/reindex",
    status_code=202,
    response_model=LifecycleAccepted,
)
async def reindex_document(
    collection_id: UUID,
    document_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> LifecycleAccepted:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.REINDEX):
        raise HTTPException(status_code=403, detail="Permission denied")
    locked = await session.scalar(
        select(Document).where(Document.id == document.id).with_for_update()
    )
    if (
        locked is None
        or locked.status != DocumentStatus.AVAILABLE
        or locked.active_version_id is None
    ):
        raise HTTPException(status_code=409, detail="Document has no active source")
    version = await session.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == locked.active_version_id,
            DocumentVersion.tenant_id == locked.tenant_id,
            DocumentVersion.document_id == locked.id,
        )
        .with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=409, detail="Document has no active source")
    settings = get_settings()
    config = index_configuration(version.content_type, settings)
    existing = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == locked.tenant_id,
            ProcessingJob.document_id == locked.id,
            ProcessingJob.operation == "reindex",
            ProcessingJob.idempotency_key == idempotency_key,
        )
    )
    if existing:
        if existing.request_fingerprint != config.fingerprint:
            raise HTTPException(
                status_code=409, detail="Idempotency key payload conflict"
            )
        return LifecycleAccepted(
            document_id=locked.id,
            version_id=existing.document_version_id,
            generation_id=existing.generation_id,
            job_id=existing.id,
            processing_status=existing.status.value,
        )
    active_operation = await session.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.tenant_id == locked.tenant_id,
            ProcessingJob.document_id == locked.id,
            ProcessingJob.operation.in_(("replacement_ingestion", "reindex")),
            ProcessingJob.status.in_(
                (
                    ProcessingJobStatus.QUEUED,
                    ProcessingJobStatus.RUNNING,
                    ProcessingJobStatus.RETRYING,
                )
            ),
        )
    )
    if active_operation is not None:
        raise HTTPException(
            status_code=409, detail="Document lifecycle operation in progress"
        )
    number = (
        int(
            await session.scalar(
                select(
                    func.coalesce(
                        func.max(DocumentIndexGeneration.generation_number), 0
                    )
                ).where(DocumentIndexGeneration.document_version_id == version.id)
            )
            or 0
        )
        + 1
    )
    generation_id, job_id = uuid4(), uuid4()
    generation = DocumentIndexGeneration(
        id=generation_id,
        tenant_id=locked.tenant_id,
        document_id=locked.id,
        document_version_id=version.id,
        generation_number=number,
        requested_by_user_id=principal.user_id,
        processing_job_id=job_id,
        **config.__dict__,
        configuration_fingerprint=config.fingerprint,
    )
    job = ProcessingJob(
        id=job_id,
        tenant_id=locked.tenant_id,
        document_id=locked.id,
        document_version_id=version.id,
        generation_id=generation_id,
        requested_by_user_id=principal.user_id,
        operation="reindex",
        idempotency_key=idempotency_key,
        request_fingerprint=config.fingerprint,
    )
    session.add(generation)
    await session.flush()
    session.add(job)
    session.add(
        business_audit_event(
            locked.tenant_id,
            principal.user_id,
            None,
            "document.reindex_requested",
            "document",
            locked.id,
        )
    )
    await session.commit()
    try:
        with stage("lifecycle.reindex.enqueue", {"rag.operation": "reindex"}):
            verify_original_task.apply_async(
                args=[str(locked.tenant_id), str(locked.id), str(job_id)]
            )
    except Exception:
        pass
    INGESTION_QUEUE.labels("reindex").inc()
    LIFECYCLE.labels("reindex", "succeeded").inc()
    return LifecycleAccepted(
        document_id=locked.id,
        version_id=version.id,
        generation_id=generation_id,
        job_id=job_id,
        processing_status="queued",
    )


@router.delete(
    "/collections/{collection_id}/documents/{document_id}",
    status_code=202,
    response_model=LifecycleAccepted,
)
async def delete_document(
    collection_id: UUID,
    document_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> LifecycleAccepted:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.DELETE_DOCUMENT):
        raise HTTPException(status_code=403, detail="Permission denied")
    existing = await session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == document.tenant_id,
            ProcessingJob.document_id == document.id,
            ProcessingJob.operation == "document_deletion",
        )
    )
    if existing:
        return LifecycleAccepted(
            document_id=document.id,
            job_id=existing.id,
            processing_status=existing.status.value,
        )
    locked = await session.scalar(
        select(Document).where(Document.id == document.id).with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Document not found")
    job = ProcessingJob(
        id=uuid4(),
        tenant_id=locked.tenant_id,
        document_id=locked.id,
        requested_by_user_id=principal.user_id,
        operation="document_deletion",
        idempotency_key="document-deletion",
        request_fingerprint=_fingerprint(locked.id),
    )
    locked.status = DocumentStatus.DELETING
    session.add(job)
    session.add(
        business_audit_event(
            locked.tenant_id,
            principal.user_id,
            None,
            "document.deletion_requested",
            "document",
            locked.id,
        )
    )
    await session.commit()
    try:
        delete_document_task.apply_async(
            args=[str(locked.tenant_id), str(locked.id), str(job.id)]
        )
    except Exception:
        pass
    INGESTION_QUEUE.labels("deletion").inc()
    return LifecycleAccepted(
        document_id=locked.id, job_id=job.id, processing_status="queued"
    )


@router.get(
    "/collections/{collection_id}/documents",
    response_model=list[DocumentListItem],
)
async def list_documents(
    collection_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DocumentListItem]:
    await require_collection_permission(
        session, principal.user_id, collection_id, CollectionPermission.READ
    )
    rows = (
        await session.execute(
            select(Document, DocumentVersion)
            .outerjoin(
                DocumentVersion, DocumentVersion.id == Document.active_version_id
            )
            .where(Document.collection_id == collection_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
    ).all()
    return [
        DocumentListItem(
            id=document.id,
            collection_id=document.collection_id,
            status=document.status.value,
            active_version_id=document.active_version_id,
            deleted=document.status == DocumentStatus.DELETED,
            filename=version.filename if version else None,
            content_type=version.content_type if version else None,
            active_version_number=version.version_number if version else None,
            active_generation_id=version.active_generation_id if version else None,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
        for document, version in rows
    ]


@router.get(
    "/collections/{collection_id}/documents/{document_id}",
    response_model=DocumentInfo,
)
async def get_document(
    collection_id: UUID,
    document_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.READ):
        raise HTTPException(status_code=403, detail="Permission denied")
    return DocumentInfo(
        id=document.id,
        collection_id=document.collection_id,
        status=document.status.value,
        active_version_id=document.active_version_id,
        deleted=document.status == DocumentStatus.DELETED,
    )


@router.get(
    "/collections/{collection_id}/documents/{document_id}/versions",
    response_model=list[VersionInfo],
)
async def list_versions(
    collection_id: UUID,
    document_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[VersionInfo]:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.READ):
        raise HTTPException(status_code=403, detail="Permission denied")
    versions = (
        await session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == document.tenant_id,
                DocumentVersion.document_id == document.id,
            )
            .order_by(DocumentVersion.version_number)
        )
    ).all()
    return [
        VersionInfo(
            id=v.id,
            version_number=v.version_number,
            status=v.status.value,
            active=v.id == document.active_version_id,
            checksum_sha256=v.checksum_sha256,
            filename=v.filename,
            content_type=v.content_type,
            size_bytes=v.size_bytes,
            metadata=v.document_metadata,
            active_generation_id=v.active_generation_id,
            failure_category=v.failure_category,
        )
        for v in versions
    ]


@router.get(
    "/collections/{collection_id}/documents/{document_id}/versions/{version_id}",
    response_model=dict[str, object],
)
async def get_version(
    collection_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.READ):
        raise HTTPException(status_code=403, detail="Permission denied")
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.tenant_id == document.tenant_id,
            DocumentVersion.document_id == document.id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    generations = (
        await session.scalars(
            select(DocumentIndexGeneration)
            .where(
                DocumentIndexGeneration.tenant_id == document.tenant_id,
                DocumentIndexGeneration.document_id == document.id,
                DocumentIndexGeneration.document_version_id == version.id,
            )
            .order_by(DocumentIndexGeneration.generation_number)
        )
    ).all()
    info = VersionInfo(
        id=version.id,
        version_number=version.version_number,
        status=version.status.value,
        active=version.id == document.active_version_id,
        checksum_sha256=version.checksum_sha256,
        filename=version.filename,
        content_type=version.content_type,
        size_bytes=version.size_bytes,
        metadata=version.document_metadata,
        active_generation_id=version.active_generation_id,
        failure_category=version.failure_category,
    )
    return {
        **info.model_dump(mode="json"),
        "generations": [
            GenerationInfo(
                id=g.id,
                generation_number=g.generation_number,
                status=g.status.value,
                configuration_fingerprint=g.configuration_fingerprint,
                parser_version=g.parser_version,
                cleaner_version=g.cleaner_version,
                chunker_version=g.chunker_version,
                embedding_input_version=g.embedding_input_version,
                embedding_provider=g.embedding_provider,
                embedding_model=g.embedding_model,
                embedding_dimensions=g.embedding_dimensions,
                text_search_configuration=g.text_search_configuration,
                failure_category=g.failure_category,
            ).model_dump(mode="json")
            for g in generations
        ],
    }


@router.get(
    "/collections/{collection_id}/documents/{document_id}/versions/{version_id}/source",
    response_class=FileResponse,
)
async def get_version_source(
    collection_id: UUID,
    document_id: UUID,
    version_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    document, role = await _document_and_role(
        session, principal, collection_id, document_id
    )
    if not has_permission(role, Permission.READ):
        raise HTTPException(status_code=403, detail="Permission denied")
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.tenant_id == document.tenant_id,
            DocumentVersion.document_id == document.id,
        )
    )
    if version is None or document.status in {
        DocumentStatus.DELETING,
        DocumentStatus.DELETED,
    }:
        raise HTTPException(status_code=404, detail="Document source not found")
    storage = LocalDocumentStorage(get_settings().document_storage_path)
    source = storage.path_for_validation(version.storage_key)
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Document source not found")
    return FileResponse(
        source,
        media_type=version.content_type,
        filename=version.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
