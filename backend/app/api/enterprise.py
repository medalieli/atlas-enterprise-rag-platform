import csv
import io
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    CollectionPermission,
    ExternalIdentity,
    Permission,
    TrustedPrincipal,
    get_trusted_principal,
    require_collection_permission,
    require_membership,
    verify_external_identity,
)
from app.core.config import get_settings
from app.db.models import (
    AnswerFeedback,
    AuditEvent,
    Collection,
    CollectionGrant,
    CollectionRole,
    Conversation,
    ConversationMessage,
    ConversationMessageRole,
    ConversationTurn,
    Document,
    DocumentChunk,
    DocumentStatus,
    DocumentVersion,
    Invitation,
    Membership,
    MembershipRole,
    ProcessingJob,
    ProcessingJobStatus,
    User,
)
from app.db.session import get_session
from app.observability import request_id_var

router = APIRouter(tags=["enterprise administration"])


class GrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: UUID
    role: CollectionRole


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    role: MembershipRole = MembershipRole.MEMBER
    grants: list[GrantInput] = Field(default_factory=list, max_length=50)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("email must be a valid address")
        return normalized


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=512)


class InvitationUpdate(InvitationCreate):
    pass


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: MembershipRole | None = None
    membership_status: Literal["active", "suspended", "revoked"] | None = None
    expected_version: int = Field(ge=1)


class GrantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: CollectionRole


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["helpful", "not_helpful"]
    reason: (
        Literal[
            "incorrect",
            "incomplete",
            "irrelevant_sources",
            "citation_problem",
            "outdated_source",
            "other",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_reason(self):
        if self.rating == "helpful" and self.reason is not None:
            raise ValueError("helpful feedback cannot include a negative reason")
        return self


async def _admin(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    permission: Permission = Permission.MANAGE_MEMBERS,
) -> Membership:
    return await require_membership(session, user_id, tenant_id, permission)


async def _grant_manager(
    session: AsyncSession,
    principal: TrustedPrincipal,
    tenant_id: UUID,
    collection_id: UUID,
) -> str:
    (
        actual_tenant,
        organization_role,
        collection_role,
    ) = await require_collection_permission(
        session,
        principal.user_id,
        collection_id,
        CollectionPermission.MANAGE_GRANTS,
    )
    if actual_tenant != tenant_id:
        raise HTTPException(404, "Collection not found")
    return collection_role.value if collection_role else organization_role.value


def _audit(
    tenant_id: UUID,
    actor: UUID | None,
    role: str | None,
    action: str,
    target_type: str,
    target_id: UUID | None,
    outcome: str = "success",
    metadata: dict[str, object] | None = None,
) -> AuditEvent:
    safe = {
        k: v
        for k, v in (metadata or {}).items()
        if k in {"reason_code", "new_role", "new_status", "collection_role"}
        and isinstance(v, str | bool | int)
    }
    return AuditEvent(
        tenant_id=tenant_id,
        actor_user_id=actor,
        actor_role=role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        request_id=request_id_var.get(),
        event_metadata=safe,
    )


def business_audit_event(
    tenant_id: UUID,
    actor: UUID | None,
    role: str | None,
    action: str,
    target_type: str,
    target_id: UUID | None,
) -> AuditEvent:
    """Build a bounded event without accepting user or document content."""
    return _audit(tenant_id, actor, role, action, target_type, target_id)


def _member(item: Membership, user: User) -> dict[str, object]:
    return {
        "id": item.id,
        "principal_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": item.role.value,
        "status": item.status,
        "version": item.version,
        "created_at": item.created_at,
    }


@router.get("/organizations/{tenant_id}/members")
async def members(
    tenant_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
):
    await _admin(session, principal.user_id, tenant_id)
    query = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id)
    )
    if cursor:
        query = query.where(Membership.id > cursor)
    rows = (await session.execute(query.order_by(Membership.id).limit(limit + 1))).all()
    return {
        "items": [_member(m, u) for m, u in rows[:limit]],
        "next_cursor": rows[limit][0].id if len(rows) > limit else None,
    }


@router.patch("/organizations/{tenant_id}/members/{membership_id}")
async def update_member(
    tenant_id: UUID,
    membership_id: UUID,
    request: MemberUpdate,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor = await _admin(session, principal.user_id, tenant_id)
    target = await session.scalar(
        select(Membership)
        .where(Membership.id == membership_id, Membership.tenant_id == tenant_id)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(404, "Member not found")
    if target.user_id == principal.user_id:
        raise HTTPException(403, "Users cannot change their own authorization")
    if request.expected_version != target.version:
        raise HTTPException(409, "Membership changed; reload and retry")
    if request.role == MembershipRole.OWNER and actor.role != MembershipRole.OWNER:
        raise HTTPException(403, "Only owners manage owners")
    removing_owner = target.role == MembershipRole.OWNER and (
        request.role not in {None, MembershipRole.OWNER}
        or request.membership_status in {"suspended", "revoked"}
    )
    if removing_owner:
        owners = await session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == MembershipRole.OWNER,
                Membership.status == "active",
                Membership.enabled.is_(True),
            )
        )
        if owners == 1:
            raise HTTPException(409, "The final active owner cannot be removed")
    if request.role is not None:
        target.role = request.role
    if request.membership_status is not None:
        target.status = request.membership_status
        target.enabled = request.membership_status == "active"
    target.version += 1
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "membership.changed",
            "membership",
            target.id,
            metadata={"new_role": target.role.value, "new_status": target.status},
        )
    )
    await session.commit()
    return {
        "id": target.id,
        "role": target.role.value,
        "status": target.status,
        "version": target.version,
    }


@router.post(
    "/organizations/{tenant_id}/invitations", status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    tenant_id: UUID,
    request: InvitationCreate,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor = await _admin(session, principal.user_id, tenant_id)
    actor_user = await session.get(User, principal.user_id)
    if actor_user is None:
        raise HTTPException(403, "Invitation issuer is unavailable")
    if request.role == MembershipRole.OWNER and actor.role != MembershipRole.OWNER:
        raise HTTPException(403, "Only owners may invite owners")
    collection_ids = {g.collection_id for g in request.grants}
    if collection_ids:
        valid = set(
            (
                await session.scalars(
                    select(Collection.id).where(
                        Collection.tenant_id == tenant_id,
                        Collection.id.in_(collection_ids),
                    )
                )
            ).all()
        )
        if valid != collection_ids:
            raise HTTPException(404, "Collection not found")
    pending = await session.scalar(
        select(Invitation.id).where(
            Invitation.tenant_id == tenant_id,
            Invitation.email_normalized == request.email,
            Invitation.status == "pending",
            Invitation.expires_at >= datetime.now(UTC),
        )
    )
    if pending is not None:
        raise HTTPException(409, "A pending invitation already exists")
    token = token_urlsafe(48)
    invitation = Invitation(
        tenant_id=tenant_id,
        email_normalized=str(request.email).strip().lower(),
        issuer=actor_user.issuer,
        role=request.role,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC)
        + timedelta(hours=get_settings().invitation_expiration_hours),
        created_by_user_id=principal.user_id,
        initial_grants=[
            {"collection_id": str(g.collection_id), "role": g.role.value}
            for g in request.grants
        ],
    )
    session.add(invitation)
    await session.flush()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "invitation.created",
            "invitation",
            invitation.id,
        )
    )
    await session.commit()
    return {
        "id": invitation.id,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "invitation_link": f"/invitations/accept#token={token}",
    }


@router.get("/organizations/{tenant_id}/invitations")
async def invitations(
    tenant_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
    invitation_status: Literal[
        "active", "accepted", "expired", "revoked", "removed", "all"
    ] = "active",
):
    await _admin(session, principal.user_id, tenant_id)
    now = datetime.now(UTC)
    expired = (
        await session.scalars(
            select(Invitation).where(
                Invitation.tenant_id == tenant_id,
                Invitation.status == "pending",
                Invitation.expires_at < now,
            )
        )
    ).all()
    for item in expired:
        item.status = "expired"
        session.add(
            _audit(
                tenant_id,
                None,
                None,
                "invitation.expired",
                "invitation",
                item.id,
            )
        )
    q = select(Invitation).where(Invitation.tenant_id == tenant_id)
    if invitation_status == "active":
        q = q.where(Invitation.status == "pending")
    elif invitation_status != "all":
        q = q.where(Invitation.status == invitation_status)
    if cursor:
        q = q.where(Invitation.id > cursor)
    rows = (await session.scalars(q.order_by(Invitation.id).limit(limit + 1))).all()
    await session.commit()
    return {
        "items": [
            {
                "id": i.id,
                "email": i.email_normalized,
                "issuer": i.issuer,
                "role": i.role.value,
                "status": i.status,
                "expires_at": i.expires_at,
                "created_at": i.created_at,
                "grants": i.initial_grants,
            }
            for i in rows[:limit]
        ],
        "next_cursor": rows[limit].id if len(rows) > limit else None,
    }


@router.patch("/organizations/{tenant_id}/invitations/{invitation_id}")
async def update_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    request: InvitationUpdate,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Edit pending claims, rotating the token only when the email changes."""
    actor = await _admin(session, principal.user_id, tenant_id)
    old = await session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.tenant_id == tenant_id)
        .with_for_update()
    )
    if old is None:
        raise HTTPException(404, "Invitation not found")
    if old.status != "pending":
        raise HTTPException(409, "Only pending invitations can be edited")
    if request.role == MembershipRole.OWNER and actor.role != MembershipRole.OWNER:
        raise HTTPException(403, "Only owners may invite owners")
    collection_ids = {grant.collection_id for grant in request.grants}
    if collection_ids:
        valid = set(
            (
                await session.scalars(
                    select(Collection.id).where(
                        Collection.tenant_id == tenant_id,
                        Collection.id.in_(collection_ids),
                    )
                )
            ).all()
        )
        if valid != collection_ids:
            raise HTTPException(404, "Collection not found")
    normalized_email = str(request.email).strip().lower()
    grants = [
        {"collection_id": str(g.collection_id), "role": g.role.value}
        for g in request.grants
    ]
    if normalized_email == old.email_normalized:
        old.role = request.role
        old.initial_grants = grants
        session.add(
            _audit(
                tenant_id,
                principal.user_id,
                actor.role.value,
                "invitation.edited",
                "invitation",
                old.id,
                metadata={"new_role": request.role.value, "token_rotated": False},
            )
        )
        await session.commit()
        return {
            "id": old.id,
            "status": old.status,
            "expires_at": old.expires_at,
            "invitation_link": None,
            "token_rotated": False,
        }

    old.status = "replaced"
    token = token_urlsafe(48)
    replacement = Invitation(
        tenant_id=tenant_id,
        email_normalized=normalized_email,
        issuer=old.issuer,
        role=request.role,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC)
        + timedelta(hours=get_settings().invitation_expiration_hours),
        created_by_user_id=principal.user_id,
        initial_grants=grants,
    )
    session.add(replacement)
    await session.flush()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "invitation.edited",
            "invitation",
            old.id,
            metadata={"new_role": request.role.value, "token_rotated": True},
        )
    )
    await session.commit()
    return {
        "id": replacement.id,
        "status": replacement.status,
        "expires_at": replacement.expires_at,
        "invitation_link": f"/invitations/accept#token={token}",
        "token_rotated": True,
    }


@router.post(
    "/organizations/{tenant_id}/invitations/{invitation_id}/remove",
    status_code=204,
)
async def remove_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor = await _admin(session, principal.user_id, tenant_id)
    item = await session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.tenant_id == tenant_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Invitation not found")
    if item.status == "removed":
        return
    if item.status == "accepted":
        raise HTTPException(409, "Accepted users must be managed as members")
    item.status = "removed"
    item.removed_at = datetime.now(UTC)
    item.revoked_at = item.revoked_at or item.removed_at
    item.token_hash = sha256(token_urlsafe(48).encode()).hexdigest()
    item.email_normalized = f"removed-{item.id}@redacted.invalid"
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "invitation.removed",
            "invitation",
            item.id,
        )
    )
    await session.commit()


@router.post("/organizations/{tenant_id}/invitations/{invitation_id}/replace")
async def replace_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor = await _admin(session, principal.user_id, tenant_id)
    old = await session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.tenant_id == tenant_id)
        .with_for_update()
    )
    if old is None:
        raise HTTPException(404, "Invitation not found")
    if old.status not in {"pending", "expired"}:
        raise HTTPException(409, "Invitation cannot be replaced")
    old.status = "replaced"
    token = token_urlsafe(48)
    replacement = Invitation(
        tenant_id=tenant_id,
        email_normalized=old.email_normalized,
        issuer=old.issuer,
        role=old.role,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC)
        + timedelta(hours=get_settings().invitation_expiration_hours),
        created_by_user_id=principal.user_id,
        initial_grants=old.initial_grants,
    )
    session.add(replacement)
    await session.flush()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "invitation.replaced",
            "invitation",
            old.id,
        )
    )
    await session.commit()
    return {
        "id": replacement.id,
        "status": replacement.status,
        "expires_at": replacement.expires_at,
        "invitation_link": f"/invitations/accept#token={token}",
    }


@router.delete(
    "/organizations/{tenant_id}/invitations/{invitation_id}", status_code=204
)
async def revoke_invitation(
    tenant_id: UUID,
    invitation_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor = await _admin(session, principal.user_id, tenant_id)
    item = await session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.tenant_id == tenant_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Invitation not found")
    if item.status != "pending":
        raise HTTPException(409, "Invitation is not pending")
    item.status = "revoked"
    item.revoked_at = datetime.now(UTC)
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "invitation.revoked",
            "invitation",
            item.id,
        )
    )
    await session.commit()


@router.post("/invitations/accept")
async def accept_invitation(
    request: InvitationAccept,
    identity: Annotated[ExternalIdentity, Depends(verify_external_identity)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if not identity.email_verified or not identity.email:
        raise HTTPException(403, "A verified provider email is required")
    digest = sha256(request.token.encode()).hexdigest()
    item = await session.scalar(
        select(Invitation).where(Invitation.token_hash == digest).with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Invitation not found")
    if item.attempt_count >= 10:
        raise HTTPException(410, "Invitation is unavailable")
    if item.status == "accepted":
        accepted_user = await session.get(User, item.accepted_by_user_id)
        if (
            accepted_user is not None
            and accepted_user.issuer == identity.issuer
            and accepted_user.subject == identity.subject
        ):
            return {
                "tenant_id": item.tenant_id,
                "membership_id": await session.scalar(
                    select(Membership.id).where(
                        Membership.tenant_id == item.tenant_id,
                        Membership.user_id == accepted_user.id,
                    )
                ),
                "status": "accepted",
                "idempotent": True,
            }
        raise HTTPException(410, "Invitation is unavailable")
    item.attempt_count += 1
    if item.status == "pending" and item.expires_at <= datetime.now(UTC):
        item.status = "expired"
        session.add(
            _audit(
                item.tenant_id,
                None,
                None,
                "invitation.expired",
                "invitation",
                item.id,
            )
        )
    if item.status != "pending":
        await session.commit()
        raise HTTPException(410, "Invitation is unavailable")
    if (
        item.issuer != identity.issuer
        or item.email_normalized != identity.email.strip().lower()
    ):
        await session.commit()
        raise HTTPException(403, "Invitation identity does not match")
    user = await session.scalar(
        select(User)
        .where(User.issuer == identity.issuer, User.subject == identity.subject)
        .with_for_update()
    )
    if user is None:
        user = User(
            issuer=identity.issuer,
            subject=identity.subject,
            email=identity.email,
            enabled=True,
        )
        session.add(user)
        await session.flush()
    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == item.tenant_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        membership = Membership(
            tenant_id=item.tenant_id,
            user_id=user.id,
            role=item.role,
            status="active",
            enabled=True,
        )
        session.add(membership)
        await session.flush()
    elif membership.status == "revoked":
        await session.commit()
        raise HTTPException(409, "Membership cannot be reactivated by invitation")
    for grant in item.initial_grants:
        collection_id = UUID(grant["collection_id"])
        existing_grant = await session.scalar(
            select(CollectionGrant).where(
                CollectionGrant.tenant_id == item.tenant_id,
                CollectionGrant.collection_id == collection_id,
                CollectionGrant.membership_id == membership.id,
            )
        )
        if existing_grant is None:
            session.add(
                CollectionGrant(
                    tenant_id=item.tenant_id,
                    collection_id=collection_id,
                    membership_id=membership.id,
                    role=CollectionRole(grant["role"]),
                    created_by_user_id=item.created_by_user_id,
                )
            )
    item.status = "accepted"
    item.accepted_at = datetime.now(UTC)
    item.accepted_by_user_id = user.id
    session.add(
        _audit(
            item.tenant_id,
            user.id,
            membership.role.value,
            "invitation.accepted",
            "invitation",
            item.id,
        )
    )
    await session.commit()
    return {
        "tenant_id": item.tenant_id,
        "membership_id": membership.id,
        "status": "accepted",
    }


@router.put(
    "/organizations/{tenant_id}/collections/{collection_id}/grants/{membership_id}"
)
async def put_grant(
    tenant_id: UUID,
    collection_id: UUID,
    membership_id: UUID,
    request: GrantUpdate,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor_role = await _grant_manager(session, principal, tenant_id, collection_id)
    collection = await session.scalar(
        select(Collection.id).where(
            Collection.id == collection_id, Collection.tenant_id == tenant_id
        )
    )
    member = await session.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
        )
    )
    if collection is None or member is None:
        raise HTTPException(404, "Collection or member not found")
    grant = await session.scalar(
        select(CollectionGrant).where(
            CollectionGrant.tenant_id == tenant_id,
            CollectionGrant.collection_id == collection_id,
            CollectionGrant.membership_id == membership_id,
        )
    )
    if grant is None:
        grant = CollectionGrant(
            tenant_id=tenant_id,
            collection_id=collection_id,
            membership_id=membership_id,
            role=request.role,
            created_by_user_id=principal.user_id,
        )
        session.add(grant)
    else:
        grant.role = request.role
    await session.flush()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor_role,
            "collection_grant.changed",
            "collection_grant",
            grant.id,
            metadata={"collection_role": request.role.value},
        )
    )
    await session.commit()
    return {
        "id": grant.id,
        "collection_id": collection_id,
        "membership_id": membership_id,
        "role": grant.role.value,
    }


@router.delete(
    "/organizations/{tenant_id}/collections/{collection_id}/grants/{membership_id}",
    status_code=204,
)
async def delete_grant(
    tenant_id: UUID,
    collection_id: UUID,
    membership_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    actor_role = await _grant_manager(session, principal, tenant_id, collection_id)
    grant = await session.scalar(
        select(CollectionGrant).where(
            CollectionGrant.tenant_id == tenant_id,
            CollectionGrant.collection_id == collection_id,
            CollectionGrant.membership_id == membership_id,
        )
    )
    if grant is None:
        raise HTTPException(404, "Grant not found")
    event_id = grant.id
    await session.delete(grant)
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor_role,
            "collection_grant.removed",
            "collection_grant",
            event_id,
        )
    )
    await session.commit()


@router.get("/organizations/{tenant_id}/collections/{collection_id}/grants")
async def list_grants(
    tenant_id: UUID,
    collection_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
):
    await _grant_manager(session, principal, tenant_id, collection_id)
    query = select(CollectionGrant).where(
        CollectionGrant.tenant_id == tenant_id,
        CollectionGrant.collection_id == collection_id,
    )
    if cursor:
        query = query.where(CollectionGrant.id > cursor)
    rows = (
        await session.scalars(query.order_by(CollectionGrant.id).limit(limit + 1))
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "membership_id": item.membership_id,
                "role": item.role.value,
            }
            for item in rows[:limit]
        ],
        "next_cursor": rows[limit].id if len(rows) > limit else None,
    }


@router.get("/organizations/{tenant_id}/audit-events")
async def audit_events(
    tenant_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: UUID | None = None,
    actor_id: UUID | None = None,
    action: str | None = Query(None, max_length=100),
    target_type: str | None = Query(None, max_length=50),
    outcome: Literal["success", "denied", "failure"] | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    actor = await _admin(session, principal.user_id, tenant_id, Permission.VIEW_AUDIT)
    q = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    if cursor:
        q = q.where(AuditEvent.id < cursor)
    if actor_id:
        selected_member = await session.scalar(
            select(Membership.user_id).where(
                Membership.id == actor_id, Membership.tenant_id == tenant_id
            )
        )
        q = q.where(AuditEvent.actor_user_id == (selected_member or actor_id))
    if action:
        q = q.where(AuditEvent.action == action)
    if target_type:
        q = q.where(AuditEvent.target_type == target_type)
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    if from_date:
        q = q.where(AuditEvent.created_at >= from_date)
    if to_date:
        q = q.where(AuditEvent.created_at <= to_date)
    if from_date and to_date and (to_date - from_date) > timedelta(days=366):
        raise HTTPException(422, "Audit date range cannot exceed 366 days")
    rows = (
        await session.scalars(
            q.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(
                limit + 1
            )
        )
    ).all()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "audit.viewed",
            "audit_log",
            None,
        )
    )
    await session.commit()
    return {
        "items": [
            {
                "id": e.id,
                "actor_id": e.actor_user_id,
                "actor_role": e.actor_role,
                "action": e.action,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "outcome": e.outcome,
                "request_id": e.request_id,
                "metadata": e.event_metadata,
                "created_at": e.created_at,
            }
            for e in rows[:limit]
        ],
        "next_cursor": rows[limit].id if len(rows) > limit else None,
    }


def _csv_safe(value: object | None) -> str:
    text_value = "" if value is None else str(value)
    if text_value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text_value
    return text_value


@router.get("/organizations/{tenant_id}/audit-events/export")
async def export_audit_events(
    tenant_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    actor_id: UUID | None = None,
    action: str | None = Query(None, max_length=100),
    target_type: str | None = Query(None, max_length=50),
    outcome: Literal["success", "denied", "failure"] | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    actor = await _admin(session, principal.user_id, tenant_id, Permission.VIEW_AUDIT)
    settings = get_settings()
    now = datetime.now(UTC)
    start = from_date or now - timedelta(days=30)
    end = to_date or now
    if start > end:
        raise HTTPException(422, "Audit start must not follow end")
    if end - start > timedelta(days=settings.audit_export_max_days):
        raise HTTPException(
            422,
            f"Audit export range cannot exceed {settings.audit_export_max_days} days",
        )
    previous = await session.scalar(
        select(func.max(AuditEvent.created_at)).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.actor_user_id == principal.user_id,
            AuditEvent.action == "audit.exported",
        )
    )
    if previous is not None and now - previous < timedelta(
        seconds=settings.audit_export_rate_limit_seconds
    ):
        raise HTTPException(429, "Audit export rate limit exceeded")
    q = (
        select(AuditEvent, User)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at >= start,
            AuditEvent.created_at <= end,
        )
    )
    if actor_id:
        selected_member = await session.scalar(
            select(Membership.user_id).where(
                Membership.id == actor_id, Membership.tenant_id == tenant_id
            )
        )
        q = q.where(AuditEvent.actor_user_id == (selected_member or actor_id))
    if action:
        q = q.where(AuditEvent.action == action)
    if target_type:
        q = q.where(AuditEvent.target_type == target_type)
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    rows = (
        await session.execute(
            q.order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc()).limit(
                settings.audit_export_max_rows + 1
            )
        )
    ).all()
    if len(rows) > settings.audit_export_max_rows:
        raise HTTPException(
            422,
            "Audit export exceeds the configured row limit; narrow the filters",
        )
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "audit.exported",
            "audit_log",
            None,
        )
    )
    await session.commit()

    def csv_rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            (
                "timestamp_utc",
                "actor",
                "action",
                "target_type",
                "target_id",
                "outcome",
                "request_id",
            )
        )
        yield buffer.getvalue()
        for event, event_actor in rows:
            buffer.seek(0)
            buffer.truncate(0)
            identity = (
                event_actor.display_name
                or event_actor.email
                or str(event.actor_user_id)
                if event_actor is not None
                else "Anonymized identity"
            )
            writer.writerow(
                tuple(
                    _csv_safe(value)
                    for value in (
                        event.created_at.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        identity,
                        event.action,
                        event.target_type,
                        event.target_id,
                        event.outcome,
                        event.request_id,
                    )
                )
            )
            yield buffer.getvalue()

    filename = f"atlas-audit-{start.date().isoformat()}-to-{end.date().isoformat()}.csv"
    return StreamingResponse(
        csv_rows(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/collections/{collection_id}/conversations/{conversation_id}/messages/{message_id}/feedback"
)
async def feedback(
    collection_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    request: FeedbackInput,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await require_collection_permission(
        session, principal.user_id, collection_id, CollectionPermission.READ
    )
    row = (
        await session.execute(
            select(Conversation.tenant_id, ConversationMessage)
            .join(
                ConversationMessage,
                ConversationMessage.conversation_id == Conversation.id,
            )
            .join(
                Membership,
                (Membership.tenant_id == Conversation.tenant_id)
                & (Membership.user_id == principal.user_id),
            )
            .where(
                Conversation.id == conversation_id,
                Conversation.collection_id == collection_id,
                Conversation.created_by_user_id == principal.user_id,
                ConversationMessage.id == message_id,
                ConversationMessage.role == ConversationMessageRole.ASSISTANT,
                Membership.status == "active",
                Membership.enabled.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Answer not found")
    tenant_id, _ = row
    item = await session.scalar(
        select(AnswerFeedback).where(
            AnswerFeedback.tenant_id == tenant_id,
            AnswerFeedback.user_id == principal.user_id,
            AnswerFeedback.assistant_message_id == message_id,
        )
    )
    action = "feedback.created"
    if item is None:
        item = AnswerFeedback(
            tenant_id=tenant_id,
            collection_id=collection_id,
            conversation_id=conversation_id,
            user_id=principal.user_id,
            assistant_message_id=message_id,
            rating=request.rating,
            reason=request.reason,
        )
        session.add(item)
    else:
        item.rating = request.rating
        item.reason = request.reason
        action = "feedback.changed"
    await session.flush()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            None,
            action,
            "answer_feedback",
            item.id,
            metadata={"reason_code": request.reason or "none"},
        )
    )
    await session.commit()
    return {"id": item.id, "rating": item.rating, "reason": item.reason}


@router.get("/organizations/{tenant_id}/analytics")
async def analytics(
    tenant_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    collection_id: UUID | None = None,
):
    actor = await _admin(
        session, principal.user_id, tenant_id, Permission.VIEW_ANALYTICS
    )
    since = datetime.now(UTC) - timedelta(days=days)
    if (
        collection_id
        and await session.scalar(
            select(Collection.id).where(
                Collection.id == collection_id, Collection.tenant_id == tenant_id
            )
        )
        is None
    ):
        raise HTTPException(404, "Collection not found")
    total_users = await session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(Membership.tenant_id == tenant_id)
    )
    active_users = await session.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.enabled.is_(True),
        )
    )
    roles = dict(
        (
            await session.execute(
                select(Membership.role, func.count())
                .where(Membership.tenant_id == tenant_id)
                .group_by(Membership.role)
            )
        ).all()
    )
    collections = await session.scalar(
        select(func.count())
        .select_from(Collection)
        .where(Collection.tenant_id == tenant_id)
    )
    doc_where = [Document.tenant_id == tenant_id] + (
        [Document.collection_id == collection_id] if collection_id else []
    )
    docs = dict(
        (
            await session.execute(
                select(Document.status, func.count())
                .where(*doc_where)
                .group_by(Document.status)
            )
        ).all()
    )
    chunks = await session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*doc_where)
    )
    versions = await session.scalar(
        select(func.count())
        .select_from(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(*doc_where)
    )
    turn_where = [
        ConversationTurn.tenant_id == tenant_id,
        ConversationTurn.created_at >= since,
    ] + ([ConversationTurn.collection_id == collection_id] if collection_id else [])
    turns = (await session.scalars(select(ConversationTurn).where(*turn_where))).all()
    statuses: dict[str, int] = {}
    latencies: list[float] = []
    for turn in turns:
        response = turn.response or {}
        answer = response.get("answer") if isinstance(response, dict) else None
        answer_status = answer.get("status") if isinstance(answer, dict) else None
        if isinstance(answer_status, str):
            statuses[answer_status] = statuses.get(answer_status, 0) + 1
        latency = (
            answer.get("latency", {}).get("total_ms")
            if isinstance(answer, dict)
            else None
        )
        if isinstance(latency, int | float):
            latencies.append(float(latency))
    feedback_where = [
        AnswerFeedback.tenant_id == tenant_id,
        AnswerFeedback.created_at >= since,
    ] + ([AnswerFeedback.collection_id == collection_id] if collection_id else [])
    feedback_counts = dict(
        (
            await session.execute(
                select(AnswerFeedback.rating, func.count())
                .where(*feedback_where)
                .group_by(AnswerFeedback.rating)
            )
        ).all()
    )
    failure_query = (
        select(func.count())
        .select_from(ProcessingJob)
        .where(
            ProcessingJob.tenant_id == tenant_id,
            ProcessingJob.status == ProcessingJobStatus.FAILED,
            ProcessingJob.created_at >= since,
        )
    )
    if collection_id:
        failure_query = failure_query.join(
            Document, Document.id == ProcessingJob.document_id
        ).where(Document.collection_id == collection_id)
    failures = await session.scalar(failure_query)
    latencies.sort()

    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        return latencies[min(len(latencies) - 1, int((len(latencies) - 1) * value))]

    positive = feedback_counts.get("helpful", 0)
    negative = feedback_counts.get("not_helpful", 0)
    recent_activity = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(10)
        )
    ).all()
    session.add(
        _audit(
            tenant_id,
            principal.user_id,
            actor.role.value,
            "analytics.viewed",
            "analytics",
            None,
        )
    )
    await session.commit()
    return {
        "period_days": days,
        "total_users": total_users,
        "active_users": active_users,
        "users_by_role": {k.value: v for k, v in roles.items()},
        "pending_invitations": await session.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.tenant_id == tenant_id, Invitation.status == "pending")
        ),
        "collections": collections,
        "active_documents": docs.get(DocumentStatus.AVAILABLE, 0),
        "archived_documents": docs.get(DocumentStatus.DELETED, 0),
        "chunks": chunks,
        "document_versions": versions,
        "questions": len(turns),
        "answer_statuses": statuses,
        "positive_feedback": positive,
        "negative_feedback": negative,
        "positive_feedback_rate": positive / (positive + negative)
        if positive + negative
        else None,
        "unanswered_questions": statuses.get("insufficient_context", 0),
        "ingestion_failures": failures,
        "median_response_ms": percentile(0.5),
        "p95_response_ms": percentile(0.95),
        "citation_validation_failures": None,
        "recent_activity": [
            {
                "action": event.action,
                "target_type": event.target_type,
                "outcome": event.outcome,
                "created_at": event.created_at,
            }
            for event in recent_activity
        ],
    }
