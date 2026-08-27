import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.db.models import Membership, MembershipRole, Organization, User
from app.db.session import dispose_engine, session_factory


async def bind_identity(
    issuer: str,
    subject: str,
    tenant_id: UUID,
    role: MembershipRole,
) -> tuple[UUID, UUID]:
    """Idempotently bind one verified external identity to one existing tenant."""
    async with session_factory() as session, session.begin():
        tenant = await session.scalar(
            select(Organization.id).where(Organization.id == tenant_id)
        )
        if tenant is None:
            raise ValueError("Tenant does not exist")
        user = await session.scalar(
            select(User).where(User.issuer == issuer, User.subject == subject)
        )
        if user is None:
            user = User(issuer=issuer, subject=subject, enabled=True)
            session.add(user)
            await session.flush()
        else:
            user.enabled = True
        membership = await session.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.tenant_id == tenant_id,
            )
        )
        if membership is None:
            membership = Membership(
                user_id=user.id,
                tenant_id=tenant_id,
                role=role,
                enabled=True,
            )
            session.add(membership)
            await session.flush()
        else:
            membership.role = role
            membership.enabled = True
        return user.id, membership.id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bind an external OAuth/OIDC identity to an existing tenant"
    )
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in MembershipRole],
    )
    arguments = parser.parse_args()
    try:
        user_id, membership_id = asyncio.run(
            bind_identity(
                arguments.issuer,
                arguments.subject,
                arguments.tenant_id,
                MembershipRole(arguments.role),
            )
        )
        print(f"principal_id={user_id} membership_id={membership_id}")
    finally:
        asyncio.run(dispose_engine())


if __name__ == "__main__":
    main()
