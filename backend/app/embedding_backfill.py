import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from app.core.config import Settings
from app.db.models import DocumentChunk
from app.db.session import session_factory
from app.embeddings import (
    EMBEDDING_INPUT_VERSION,
    EmbeddingProvider,
    build_embedding_input,
    embedding_fingerprint,
)


async def embed_pending_document(
    tenant_id: UUID,
    document_id: UUID,
    settings: Settings,
    provider: EmbeddingProvider,
) -> int:
    """Embed stale/null chunks and publish the complete document set atomically."""
    async with session_factory() as session:
        chunks = (
            await session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == document_id,
                )
                .order_by(DocumentChunk.chunk_index)
            )
        ).all()

    def fingerprint_for(chunk: DocumentChunk) -> str:
        embedding_input = build_embedding_input(chunk.content, chunk.section)
        return embedding_fingerprint(
            hashlib.sha256(embedding_input.encode()).hexdigest(),
            settings.embedding_model,
            settings.embedding_dimensions,
        )

    pending = [
        chunk
        for chunk in chunks
        if chunk.embedding_fingerprint != fingerprint_for(chunk)
    ]
    if not pending:
        return 0
    inputs = [build_embedding_input(chunk.content, chunk.section) for chunk in pending]
    vectors = await provider.embed_documents(inputs)
    if len(vectors) != len(pending):
        raise ValueError("Embedding response count mismatch")
    now = datetime.now(UTC)
    async with session_factory() as session, session.begin():
        for chunk, vector in zip(pending, vectors, strict=True):
            fingerprint = fingerprint_for(chunk)
            result = await session.execute(
                update(DocumentChunk)
                .where(
                    DocumentChunk.id == chunk.id,
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.content_hash == chunk.content_hash,
                )
                .values(
                    embedding=vector,
                    embedding_model=settings.embedding_model,
                    embedding_dimensions=settings.embedding_dimensions,
                    embedding_input_version=EMBEDDING_INPUT_VERSION,
                    embedding_fingerprint=fingerprint,
                    embedded_at=now,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("Chunk changed during embedding backfill")
    return len(pending)
