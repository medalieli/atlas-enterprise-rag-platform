from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status

from app.core.config import get_settings


@dataclass(frozen=True)
class TrustedPrincipal:
    tenant_id: UUID
    user_id: UUID


async def get_trusted_principal() -> TrustedPrincipal:
    """Temporary server-owned identity seam until Milestone 10 authentication."""
    settings = get_settings()
    if (
        settings.app_env != "development"
        or not settings.development_tenant_id
        or not settings.development_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        )
    try:
        return TrustedPrincipal(
            tenant_id=UUID(settings.development_tenant_id),
            user_id=UUID(settings.development_user_id),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=503, detail="Development identity is invalid"
        ) from exc
