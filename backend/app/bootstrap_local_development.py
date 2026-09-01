"""Idempotently create the disposable local-development Owner workspace."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

from sqlalchemy import select

from app.bootstrap_identity import bind_identity
from app.db.models import Collection, MembershipRole, Organization
from app.db.session import dispose_engine, session_factory

TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
COLLECTION_ID = UUID("22222222-2222-4222-8222-222222222222")


async def bootstrap() -> None:
    if os.getenv("APP_ENV") != "development":
        raise RuntimeError("Local bootstrap is permitted only in development")
    issuer = os.environ["LOCAL_OIDC_ISSUER"]
    subject = os.getenv("LOCAL_OIDC_OWNER_SUBJECT", "local-owner")
    async with session_factory() as session, session.begin():
        organization = await session.get(Organization, TENANT_ID)
        if organization is None:
            session.add(
                Organization(
                    id=TENANT_ID,
                    name="Atlas Local Workspace",
                    slug="atlas-local",
                )
            )
        collection = await session.scalar(
            select(Collection).where(Collection.id == COLLECTION_ID)
        )
        if collection is None:
            session.add(
                Collection(
                    id=COLLECTION_ID,
                    tenant_id=TENANT_ID,
                    name="Getting Started",
                )
            )
    await bind_identity(issuer, subject, TENANT_ID, MembershipRole.OWNER)


async def run() -> None:
    try:
        await bootstrap()
        print(f"local_development_ready tenant_id={TENANT_ID}")
    finally:
        await dispose_engine()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
