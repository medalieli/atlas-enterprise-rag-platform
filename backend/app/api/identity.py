from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.enterprise import business_audit_event
from app.auth import (
    DEMO_ROLE_PERMISSIONS,
    ROLE_PERMISSIONS,
    DemoRole,
    Permission,
    TrustedPrincipal,
    get_trusted_principal,
    require_membership,
)
from app.core.config import get_settings
from app.db.models import (
    Collection,
    CollectionDeletion,
    CollectionGrant,
    Document,
    DocumentVersion,
    Membership,
    MembershipRole,
)
from app.db.session import get_session
from app.storage import LocalDocumentStorage

router = APIRouter(tags=["identity and collections"])


class MembershipResponse(BaseModel):
    tenant_id: UUID
    role: str
    permissions: list[str]
    status: str
    version: int
    real_role: str


class IdentityResponse(BaseModel):
    principal_id: UUID
    memberships: list[MembershipResponse]
    demo_role_preview_enabled: bool
    effective_demo_role: DemoRole | None


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)


class CollectionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str | None
    access_role: str


@router.get("/auth/me", response_model=IdentityResponse)
async def me(
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IdentityResponse:
    memberships = (
        await session.scalars(
            select(Membership)
            .where(
                Membership.user_id == principal.user_id,
                Membership.enabled.is_(True),
            )
            .order_by(Membership.tenant_id)
        )
    ).all()
    return IdentityResponse(
        principal_id=principal.user_id,
        demo_role_preview_enabled=get_settings().demo_role_preview_enabled,
        effective_demo_role=principal.demo_role,
        memberships=[
            MembershipResponse(
                tenant_id=item.tenant_id,
                role=(
                    principal.demo_role.value
                    if principal.demo_tenant_id == item.tenant_id
                    and principal.demo_role is not None
                    else item.role.value
                ),
                permissions=sorted(
                    permission.value
                    for permission in (
                        DEMO_ROLE_PERMISSIONS[principal.demo_role]
                        if principal.demo_tenant_id == item.tenant_id
                        and principal.demo_role is not None
                        else ROLE_PERMISSIONS[item.role]
                    )
                ),
                status=item.status,
                version=item.version,
                real_role=item.role.value,
            )
            for item in memberships
        ],
    )


@router.get("/collections", response_model=list[CollectionResponse])
async def list_collections(
    tenant_id: Annotated[UUID, Query()],
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CollectionResponse]:
    membership = await require_membership(
        session, principal.user_id, tenant_id, Permission.READ
    )
    query = select(Collection).where(Collection.tenant_id == tenant_id)
    preview_role = (
        principal.demo_role if principal.demo_tenant_id == tenant_id else None
    )
    if membership.role == MembershipRole.MEMBER and preview_role is None:
        query = query.join(
            CollectionGrant,
            (CollectionGrant.collection_id == Collection.id)
            & (CollectionGrant.tenant_id == Collection.tenant_id),
        ).where(CollectionGrant.membership_id == membership.id)
    rows = (await session.scalars(query.order_by(Collection.name, Collection.id))).all()
    grant_roles = dict(
        (
            await session.execute(
                select(CollectionGrant.collection_id, CollectionGrant.role).where(
                    CollectionGrant.membership_id == membership.id
                )
            )
        ).all()
    )
    return [
        CollectionResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            name=item.name,
            description=item.description,
            access_role=(
                {
                    DemoRole.OWNER: "manager",
                    DemoRole.ADMIN: "manager",
                    DemoRole.EDITOR: "editor",
                    DemoRole.VIEWER: "viewer",
                }[preview_role]
                if preview_role
                else "manager"
                if membership.role in {MembershipRole.OWNER, MembershipRole.ADMIN}
                else grant_roles[item.id].value
            ),
        )
        for item in rows
    ]


@router.post(
    "/collections",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    request: CollectionCreate,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CollectionResponse:
    membership = await require_membership(
        session,
        principal.user_id,
        request.tenant_id,
        Permission.MANAGE_COLLECTIONS,
    )
    existing = await session.scalar(
        select(Collection.id).where(
            Collection.tenant_id == request.tenant_id,
            Collection.name == request.name.strip(),
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Collection name already exists")
    collection = Collection(
        tenant_id=request.tenant_id,
        name=request.name.strip(),
        description=request.description,
    )
    session.add(collection)
    await session.flush()
    session.add(
        business_audit_event(
            request.tenant_id,
            principal.user_id,
            membership.role.value,
            "collection.created",
            "collection",
            collection.id,
        )
    )
    await session.commit()
    await session.refresh(collection)
    return CollectionResponse(
        id=collection.id,
        tenant_id=collection.tenant_id,
        name=collection.name,
        description=collection.description,
        access_role="manager",
    )


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    principal: Annotated[TrustedPrincipal, Depends(get_trusted_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    collection = await session.scalar(
        select(Collection).where(Collection.id == collection_id).with_for_update()
    )
    if collection is None:
        deletion = await session.scalar(
            select(CollectionDeletion)
            .join(
                Membership,
                (Membership.tenant_id == CollectionDeletion.tenant_id)
                & (Membership.user_id == principal.user_id)
                & (Membership.enabled.is_(True))
                & (Membership.status == "active"),
            )
            .where(CollectionDeletion.collection_id == collection_id)
            .with_for_update()
        )
        if deletion is None:
            raise HTTPException(status_code=404, detail="Collection not found")
        await require_membership(
            session,
            principal.user_id,
            deletion.tenant_id,
            Permission.MANAGE_COLLECTIONS,
        )
        return await _finish_collection_storage_cleanup(session, deletion)
    membership = await require_membership(
        session,
        principal.user_id,
        collection.tenant_id,
        Permission.MANAGE_COLLECTIONS,
    )
    storage_keys = list(
        (
            await session.scalars(
                select(DocumentVersion.storage_key).where(
                    DocumentVersion.collection_id == collection_id,
                    DocumentVersion.tenant_id == collection.tenant_id,
                )
            )
        ).all()
    )
    tenant_id = collection.tenant_id
    deletion = CollectionDeletion(
        tenant_id=tenant_id,
        collection_id=collection_id,
        requested_by_user_id=principal.user_id,
        storage_keys=storage_keys,
    )
    session.add(deletion)
    await session.execute(
        update(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.collection_id == collection_id,
        )
        .values(active_version_id=None)
    )
    await session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.collection_id == collection_id,
        )
        .values(active_generation_id=None)
    )
    await session.delete(collection)
    session.add(
        business_audit_event(
            tenant_id,
            principal.user_id,
            membership.role.value,
            "collection.deleted",
            "collection",
            collection_id,
        )
    )
    await session.commit()
    deletion = await session.scalar(
        select(CollectionDeletion)
        .where(CollectionDeletion.id == deletion.id)
        .with_for_update()
    )
    if deletion is None:
        raise RuntimeError("Collection cleanup state was not persisted")
    return await _finish_collection_storage_cleanup(session, deletion)


async def _finish_collection_storage_cleanup(
    session: AsyncSession, deletion: CollectionDeletion
) -> Response:
    if deletion.status == "complete":
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    storage = LocalDocumentStorage(get_settings().document_storage_path)
    try:
        for storage_key in deletion.storage_keys:
            await storage.delete(storage_key)
    except OSError as exc:
        deletion.failure_category = "storage_unavailable"
        session.add(
            business_audit_event(
                deletion.tenant_id,
                deletion.requested_by_user_id,
                None,
                "collection.cleanup_pending",
                "collection",
                deletion.collection_id,
            )
        )
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail=(
                "Collection data was removed; storage cleanup will complete on retry"
            ),
        ) from exc
    deletion.status = "complete"
    deletion.failure_category = None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
