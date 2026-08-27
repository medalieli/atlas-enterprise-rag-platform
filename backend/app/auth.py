import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from time import monotonic
from typing import Annotated
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Membership, MembershipRole, User
from app.db.session import get_session

logger = logging.getLogger("uvicorn.error")
bearer_scheme = HTTPBearer(
    bearerFormat="JWT",
    auto_error=False,
    description="OAuth 2.0 access token issued by the configured external provider",
)


class Permission(StrEnum):
    READ = "tenant:read"
    UPLOAD = "document:upload"
    REINDEX = "document:reindex"
    DELETE_DOCUMENT = "document:delete"
    MANAGE_COLLECTIONS = "collection:manage"


ROLE_PERMISSIONS: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.VIEWER: frozenset({Permission.READ}),
    MembershipRole.EDITOR: frozenset(
        {Permission.READ, Permission.UPLOAD, Permission.REINDEX}
    ),
    MembershipRole.ADMIN: frozenset(
        {
            Permission.READ,
            Permission.UPLOAD,
            Permission.REINDEX,
            Permission.DELETE_DOCUMENT,
            Permission.MANAGE_COLLECTIONS,
        }
    ),
}


@dataclass(frozen=True)
class TrustedPrincipal:
    # tenant_id is retained only for explicit test/development dependency overrides.
    tenant_id: UUID | None
    user_id: UUID


@dataclass(frozen=True)
class ExternalIdentity:
    issuer: str
    subject: str


class AuthenticationFailure(Exception):
    def __init__(self, category: str = "invalid_token") -> None:
        super().__init__("Access token could not be verified")
        self.category = category


def authentication_error(detail: str = "Invalid access token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer realm="api"'},
    )


class JWKSCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._keys: dict[str, PyJWK] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _validate_key(raw: object, algorithm: str) -> tuple[str, PyJWK] | None:
        if not isinstance(raw, dict):
            return None
        kid = raw.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            return None
        if raw.get("kty") != "RSA" or raw.get("alg") not in {None, algorithm}:
            return None
        if raw.get("use") not in {None, "sig"}:
            return None
        key_ops = raw.get("key_ops")
        if key_ops is not None and (
            not isinstance(key_ops, list) or "verify" not in key_ops
        ):
            return None
        try:
            return kid, PyJWK.from_dict(raw, algorithm=algorithm)
        except (jwt.PyJWTError, ValueError, TypeError):
            return None

    async def _refresh(self) -> None:
        settings = self.settings
        try:
            async with httpx.AsyncClient(
                timeout=settings.auth_jwks_timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    settings.auth_jwks_url or "",
                    headers={"Accept": "application/json"},
                ) as response:
                    response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if (
                        declared is not None
                        and int(declared) > settings.auth_jwks_max_bytes
                    ):
                        raise AuthenticationFailure("jwks_invalid")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > settings.auth_jwks_max_bytes:
                            raise AuthenticationFailure("jwks_invalid")
        except (httpx.HTTPError, ValueError) as exc:
            raise AuthenticationFailure("jwks_unavailable") from exc
        content = bytes(chunks)
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuthenticationFailure("jwks_invalid") from exc
        raw_keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(raw_keys, list) or len(raw_keys) > 100:
            raise AuthenticationFailure("jwks_invalid")
        validated = dict(
            item
            for raw in raw_keys
            if (item := self._validate_key(raw, settings.auth_allowed_algorithm))
        )
        if not validated:
            raise AuthenticationFailure("jwks_invalid")
        self._keys = validated
        self._expires_at = monotonic() + settings.auth_jwks_cache_seconds

    async def key(self, kid: str) -> PyJWK:
        now = monotonic()
        if now < self._expires_at and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            now = monotonic()
            refreshed = False
            if now >= self._expires_at:
                await self._refresh()
                refreshed = True
            if kid in self._keys:
                return self._keys[kid]
            # Exactly one rotation refresh for an unknown kid in this request path.
            if not refreshed:
                await self._refresh()
            key = self._keys.get(kid)
            if key is None:
                raise AuthenticationFailure("unknown_key")
            return key


class AccessTokenVerifier:
    def __init__(self, settings: Settings, cache: JWKSCache | None = None) -> None:
        self.settings = settings
        self.cache = cache or JWKSCache(settings)

    async def verify(self, token: str) -> ExternalIdentity:
        settings = self.settings
        if len(token.encode("utf-8")) > settings.auth_max_token_bytes:
            raise AuthenticationFailure("token_too_large")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthenticationFailure("malformed_token") from exc
        if header.get("alg") != settings.auth_allowed_algorithm:
            raise AuthenticationFailure("unexpected_algorithm")
        if header.get("typ") != settings.auth_expected_token_type:
            raise AuthenticationFailure("wrong_token_type")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise AuthenticationFailure("missing_key_id")
        key = await self.cache.key(kid)
        try:
            claims = await asyncio.to_thread(
                jwt.decode,
                token,
                key.key,
                algorithms=[settings.auth_allowed_algorithm],
                audience=settings.auth_audience,
                issuer=settings.auth_issuer,
                leeway=settings.auth_clock_skew_seconds,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationFailure("invalid_token") from exc
        subject = claims.get("sub")
        issued_at = claims.get("iat")
        if not isinstance(subject, str) or not subject or len(subject) > 500:
            raise AuthenticationFailure("invalid_subject")
        if not isinstance(issued_at, int) or isinstance(issued_at, bool):
            raise AuthenticationFailure("invalid_issued_at")
        if issued_at < int(time.time()) - settings.auth_max_token_age_seconds:
            raise AuthenticationFailure("token_too_old")
        scope = claims.get("scope")
        supplied_scopes = set(scope.split()) if isinstance(scope, str) else set()
        required_scopes = set(settings.auth_required_scopes.split())
        if not required_scopes.issubset(supplied_scopes):
            raise AuthenticationFailure("insufficient_scope")
        return ExternalIdentity(settings.auth_issuer or "", subject)


@lru_cache
def get_access_token_verifier() -> AccessTokenVerifier:
    return AccessTokenVerifier(get_settings())


async def get_trusted_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Security(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrustedPrincipal:
    settings = get_settings()
    if not settings.auth_enabled:
        if (
            settings.app_env not in {"development", "test"}
            or not settings.development_tenant_id
            or not settings.development_user_id
        ):
            raise authentication_error("Authentication is required")
        try:
            return TrustedPrincipal(
                tenant_id=UUID(settings.development_tenant_id),
                user_id=UUID(settings.development_user_id),
            )
        except ValueError as exc:
            raise authentication_error() from exc
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error("Authentication credentials are required")
    try:
        identity = await get_access_token_verifier().verify(credentials.credentials)
    except AuthenticationFailure as exc:
        logger.warning("Authentication failed category=%s", exc.category)
        raise authentication_error() from exc
    user = await session.scalar(
        select(User).where(
            User.issuer == identity.issuer,
            User.subject == identity.subject,
            User.enabled.is_(True),
        )
    )
    if user is None:
        raise authentication_error()
    return TrustedPrincipal(tenant_id=None, user_id=user.id)


def has_permission(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


async def require_membership(
    session: AsyncSession,
    user_id: UUID,
    tenant_id: UUID,
    permission: Permission,
) -> Membership:
    membership = await session.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.enabled.is_(True),
        )
    )
    if membership is None or not has_permission(membership.role, permission):
        raise HTTPException(status_code=403, detail="Permission denied")
    return membership
