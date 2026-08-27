from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    ROLE_PERMISSIONS,
    Permission,
    TrustedPrincipal,
    get_trusted_principal,
    require_membership,
)
from app.db.models import Collection, Membership
from app.db.session import get_session

router = APIRouter(tags=["identity and collections"])


class MembershipResponse(BaseModel):
    tenant_id: UUID
    role: str
    permissions: list[str]


class IdentityResponse(BaseModel):
    principal_id: UUID
    memberships: list[MembershipResponse]


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
        memberships=[
            MembershipResponse(
                tenant_id=item.tenant_id,
                role=item.role.value,
                permissions=sorted(
                    permission.value for permission in ROLE_PERMISSIONS[item.role]
                ),
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
    await require_membership(session, principal.user_id, tenant_id, Permission.READ)
    rows = (
        await session.scalars(
            select(Collection)
            .where(Collection.tenant_id == tenant_id)
            .order_by(Collection.name, Collection.id)
        )
    ).all()
    return [
        CollectionResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            name=item.name,
            description=item.description,
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
    await require_membership(
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
    await session.commit()
    await session.refresh(collection)
    return CollectionResponse(
        id=collection.id,
        tenant_id=collection.tenant_id,
        name=collection.name,
        description=collection.description,
    )
