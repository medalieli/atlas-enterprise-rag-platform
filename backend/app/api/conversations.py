import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.answering import AnswerGenerator
from app.api.answers import (
    AskRequest,
    AskResponse,
    ask,
    get_answer_generator_dependency,
)
from app.api.search import (
    authorize_collection,
    get_embedding_provider,
    get_reranker_dependency,
)
from app.auth import TrustedPrincipal, get_trusted_principal
from app.core.config import get_settings
from app.db.models import (
    Conversation,
    ConversationCitation,
    ConversationMessage,
    ConversationMessageRole,
    ConversationTurn,
    ConversationTurnStatus,
)
from app.db.session import get_session
from app.embeddings import EmbeddingProvider
from app.metadata import MetadataFilter
from app.reranking import RerankerProvider
from app.rewriting import (
    FollowUpRewriter,
    HistoryMessage,
    RewriteError,
    RewriteOutput,
    RewriteResult,
    RewriteStatus,
    bounded_history,
    get_follow_up_rewriter,
)

router = APIRouter(tags=["conversations"])


class CreateConversationResponse(BaseModel):
    id: UUID
    collection_id: UUID
    created_at: datetime


class ConversationSummary(CreateConversationResponse):
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    next_cursor: UUID | None


class MessageResponse(BaseModel):
    id: UUID
    sequence_number: int
    role: ConversationMessageRole
    content: str
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    next_cursor: int | None


class ConversationMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=8_000)
    top_k: int = Field(default=8, ge=1, le=20)
    filters: MetadataFilter | None = None

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class ConversationTurnResponse(BaseModel):
    conversation_id: UUID
    turn_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    turn_status: str
    rewriting_applied: bool
    standalone_query: str | None
    clarification_question: str | None = None
    rewrite_model: str
    rewrite_input_tokens: int
    rewrite_output_tokens: int
    rewrite_latency_ms: float
    answer: AskResponse | None = None


def get_rewriter_dependency() -> FollowUpRewriter | None:
    try:
        return get_follow_up_rewriter()
    except RewriteError:
        return None


async def _owned_conversation(
    session: AsyncSession,
    tenant_id: UUID,
    collection_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
) -> Conversation:
    item = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.collection_id == collection_id,
            Conversation.created_by_user_id == user_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return item


@router.post(
    "/collections/{collection_id}/conversations",
    response_model=CreateConversationResponse,
    status_code=201,
)
async def create_conversation(
    collection_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CreateConversationResponse:
    tenant_id = await authorize_collection(session, principal, collection_id)
    item = Conversation(
        tenant_id=tenant_id,
        collection_id=collection_id,
        created_by_user_id=principal.user_id,
    )
    session.add(item)
    await session.commit()
    return CreateConversationResponse(
        id=item.id, collection_id=item.collection_id, created_at=item.created_at
    )


@router.get(
    "/collections/{collection_id}/conversations",
    response_model=ConversationListResponse,
)
async def list_conversations(
    collection_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: UUID | None = None,
) -> ConversationListResponse:
    tenant_id = await authorize_collection(session, principal, collection_id)
    statement = select(Conversation).where(
        Conversation.tenant_id == tenant_id,
        Conversation.collection_id == collection_id,
        Conversation.created_by_user_id == principal.user_id,
    )
    if after is not None:
        anchor = await _owned_conversation(
            session, tenant_id, collection_id, principal.user_id, after
        )
        statement = statement.where(
            (Conversation.created_at < anchor.created_at)
            | (
                (Conversation.created_at == anchor.created_at)
                & (Conversation.id < anchor.id)
            )
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    Conversation.created_at.desc(), Conversation.id.desc()
                ).limit(limit + 1)
            )
        ).all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return ConversationListResponse(
        conversations=[
            ConversationSummary(
                id=x.id,
                collection_id=x.collection_id,
                created_at=x.created_at,
                updated_at=x.updated_at,
            )
            for x in rows
        ],
        next_cursor=rows[-1].id if more else None,
    )


@router.get(
    "/collections/{collection_id}/conversations/{conversation_id}",
    response_model=ConversationSummary,
)
async def get_conversation(
    collection_id: UUID,
    conversation_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationSummary:
    tenant_id = await authorize_collection(session, principal, collection_id)
    item = await _owned_conversation(
        session, tenant_id, collection_id, principal.user_id, conversation_id
    )
    return ConversationSummary(
        id=item.id,
        collection_id=item.collection_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get(
    "/collections/{collection_id}/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def list_messages(
    collection_id: UUID,
    conversation_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: Annotated[int, Query(ge=0)] = 0,
) -> MessageListResponse:
    tenant_id = await authorize_collection(session, principal, collection_id)
    await _owned_conversation(
        session, tenant_id, collection_id, principal.user_id, conversation_id
    )
    rows = list(
        (
            await session.scalars(
                select(ConversationMessage)
                .join(
                    ConversationTurn, ConversationTurn.id == ConversationMessage.turn_id
                )
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationTurn.status == ConversationTurnStatus.COMPLETED,
                    ConversationMessage.sequence_number > after,
                )
                .order_by(ConversationMessage.sequence_number)
                .limit(limit + 1)
            )
        ).all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return MessageListResponse(
        messages=[
            MessageResponse(
                id=x.id,
                sequence_number=x.sequence_number,
                role=x.role,
                content=x.content,
                created_at=x.created_at,
            )
            for x in rows
        ],
        next_cursor=rows[-1].sequence_number if more else None,
    )


def _fingerprint(request: ConversationMessageRequest) -> str:
    payload = request.model_dump(mode="json", exclude_none=True)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@router.post(
    "/collections/{collection_id}/conversations/{conversation_id}/messages",
    response_model=ConversationTurnResponse,
)
async def create_message(
    collection_id: UUID,
    conversation_id: UUID,
    request: ConversationMessageRequest,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    embedding_provider: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
    reranker: Annotated[RerankerProvider, Depends(get_reranker_dependency)],
    answer_generator: Annotated[
        AnswerGenerator | None, Depends(get_answer_generator_dependency)
    ],
    rewriter: Annotated[FollowUpRewriter | None, Depends(get_rewriter_dependency)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> ConversationTurnResponse:
    tenant_id = await authorize_collection(session, principal, collection_id)
    await _owned_conversation(
        session, tenant_id, collection_id, principal.user_id, conversation_id
    )
    fingerprint = _fingerprint(request)
    existing = await session.scalar(
        select(ConversationTurn).where(
            ConversationTurn.conversation_id == conversation_id,
            ConversationTurn.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409, detail="Idempotency key payload conflict"
            )
        if existing.status == ConversationTurnStatus.COMPLETED and existing.response:
            return ConversationTurnResponse.model_validate(existing.response)
        raise HTTPException(
            status_code=409, detail="Conversation turn is already processing"
        )
    sequence = (
        int(
            await session.scalar(
                select(
                    func.coalesce(func.max(ConversationTurn.sequence_number), 0)
                ).where(ConversationTurn.conversation_id == conversation_id)
            )
            or 0
        )
        + 1
    )
    turn = ConversationTurn(
        id=uuid4(),
        tenant_id=tenant_id,
        collection_id=collection_id,
        conversation_id=conversation_id,
        created_by_user_id=principal.user_id,
        sequence_number=sequence,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        original_question=request.query,
        top_k=request.top_k,
        filters=request.filters.model_dump(mode="json", exclude_none=True)
        if request.filters
        else {},
    )
    user_message = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation_id,
        turn_id=turn.id,
        sequence_number=sequence * 2 - 1,
        role=ConversationMessageRole.USER,
        content=request.query,
    )
    try:
        session.add(turn)
        await session.flush()
        session.add(user_message)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="Conversation already has an active turn"
        ) from exc
    try:
        history_rows = list(
            (
                await session.scalars(
                    select(ConversationMessage)
                    .join(
                        ConversationTurn,
                        ConversationTurn.id == ConversationMessage.turn_id,
                    )
                    .where(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationTurn.status == ConversationTurnStatus.COMPLETED,
                    )
                    .order_by(ConversationMessage.sequence_number)
                )
            ).all()
        )
        history = bounded_history(
            [HistoryMessage(x.id, x.role.value, x.content) for x in history_rows],
            get_settings(),
        )
        rewrite_started = perf_counter()
        if not history:
            rewrite = RewriteResult(
                output=RewriteOutput(
                    status=RewriteStatus.STANDALONE, standalone_query=request.query
                ),
                configured_model=get_settings().rewrite_model,
                actual_model=get_settings().rewrite_model,
                input_tokens=0,
                output_tokens=0,
            )
            rewrite_status = "bypassed"
        else:
            if rewriter is None:
                raise RewriteError("Rewrite provider unavailable")
            rewrite = await rewriter.rewrite(request.query, history)
            rewrite_status = rewrite.output.status.value
        rewrite_latency_ms = (perf_counter() - rewrite_started) * 1_000
        turn.rewrite_status = rewrite_status
        turn.standalone_question = rewrite.output.standalone_query
        turn.clarification_question = rewrite.output.clarification_question
        if rewrite.output.status == RewriteStatus.CLARIFICATION_REQUIRED:
            assistant_content = (
                rewrite.output.clarification_question or "Clarification required."
            )
            answer_response = None
        else:
            answer_response = await ask(
                collection_id,
                AskRequest(
                    query=rewrite.output.standalone_query or request.query,
                    retrieval_count=request.top_k,
                    filters=request.filters,
                ),
                principal,
                session,
                embedding_provider,
                reranker,
                answer_generator,
                request.query,
            )
            assistant_content = answer_response.answer
        assistant_message = ConversationMessage(
            conversation_id=conversation_id,
            turn_id=turn.id,
            sequence_number=sequence * 2,
            role=ConversationMessageRole.ASSISTANT,
            content=assistant_content,
            completed_at=datetime.now(UTC),
        )
        session.add(assistant_message)
        await session.flush()
        if answer_response is not None:
            session.add_all(
                [
                    ConversationCitation(
                        assistant_message_id=assistant_message.id,
                        citation_order=citation.citation_number,
                        source_id=citation.source_id,
                        chunk_id=citation.chunk_id,
                        document_id=citation.document_id,
                        document_version_id=citation.document_version_id,
                        tenant_id=tenant_id,
                        generation_id=citation.generation_id,
                        page_number=citation.page_number,
                        section_path=citation.section_path,
                        start_offset=citation.start_offset,
                        end_offset=citation.end_offset,
                        document_metadata=citation.metadata.model_dump(
                            mode="json", exclude_none=True
                        ),
                        exact_excerpt=citation.source_excerpt,
                    )
                    for citation in answer_response.citations
                ]
            )
        result = ConversationTurnResponse(
            conversation_id=conversation_id,
            turn_id=turn.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            turn_status="completed",
            rewriting_applied=rewrite_status == "rewritten",
            standalone_query=turn.standalone_question,
            clarification_question=turn.clarification_question,
            rewrite_model=rewrite.actual_model,
            rewrite_input_tokens=rewrite.input_tokens,
            rewrite_output_tokens=rewrite.output_tokens,
            rewrite_latency_ms=rewrite_latency_ms,
            answer=answer_response,
        )
        turn.status = ConversationTurnStatus.COMPLETED
        turn.completed_at = datetime.now(UTC)
        turn.response = result.model_dump(mode="json")
        await session.commit()
        return result
    except Exception as exc:
        await session.rollback()
        failed = await session.get(ConversationTurn, turn.id)
        if failed is not None:
            failed.status = ConversationTurnStatus.FAILED
            failed.failure_category = getattr(exc, "category", type(exc).__name__)[:100]
            failed.completed_at = datetime.now(UTC)
            await session.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=503, detail="Conversation turn could not be completed"
        ) from exc
