import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK

from app.auth import (
    AccessTokenVerifier,
    AuthenticationFailure,
    JWKSCache,
    Permission,
    has_permission,
)
from app.core.config import Settings
from app.db.models import CollectionRole, MembershipRole
from app.main import app

ISSUER = "https://issuer.example.test"
AUDIENCE = "rag-api"
KID = "ephemeral-test-key"


@pytest.fixture(scope="module")
def key_pair() -> tuple[object, PyJWK, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key())
    )
    public_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return private_key, PyJWK.from_dict(public_jwk, algorithm="RS256"), public_jwk


def auth_settings(**updates: object) -> Settings:
    return Settings(
        app_env="test",
        auth_enabled=True,
        auth_issuer=ISSUER,
        auth_audience=AUDIENCE,
        auth_jwks_url=f"{ISSUER}/jwks",
        **updates,
    )


class StaticCache:
    def __init__(self, key: PyJWK) -> None:
        self.value = key
        self.calls = 0

    async def key(self, kid: str) -> PyJWK:
        self.calls += 1
        if kid != KID:
            raise AuthenticationFailure("unknown_key")
        return self.value


def access_token(
    private_key: object,
    *,
    headers: dict[str, object] | None = None,
    claims: dict[str, object] | None = None,
    algorithm: str = "RS256",
) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "iss": ISSUER,
        "sub": "external-subject",
        "aud": AUDIENCE,
        "iat": now,
        "nbf": now - 1,
        "exp": now + 300,
        "scope": "rag:access",
    }
    if claims:
        payload.update(claims)
    token_headers = {"kid": KID, "typ": "at+jwt"}
    if headers:
        token_headers.update(headers)
    return jwt.encode(payload, private_key, algorithm=algorithm, headers=token_headers)


@pytest.mark.asyncio
async def test_valid_access_token_maps_external_identity(key_pair: tuple) -> None:
    private_key, public_key, _ = key_pair
    cache = StaticCache(public_key)
    identity = await AccessTokenVerifier(auth_settings(), cache).verify(
        access_token(private_key)
    )
    assert identity.issuer == ISSUER
    assert identity.subject == "external-subject"
    assert cache.calls == 1


@pytest.mark.parametrize(
    ("claims", "category"),
    [
        ({"exp": int(time.time()) - 120}, "invalid_token"),
        ({"nbf": int(time.time()) + 120}, "invalid_token"),
        ({"iat": int(time.time()) + 120}, "invalid_token"),
        ({"iss": "https://wrong.example"}, "invalid_token"),
        ({"aud": "wrong-api"}, "invalid_token"),
        ({"sub": ""}, "invalid_subject"),
        ({"scope": "different:scope"}, "insufficient_scope"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_claims_are_rejected(
    key_pair: tuple,
    claims: dict[str, object],
    category: str,
) -> None:
    private_key, public_key, _ = key_pair
    verifier = AccessTokenVerifier(auth_settings(), StaticCache(public_key))
    with pytest.raises(AuthenticationFailure) as captured:
        await verifier.verify(access_token(private_key, claims=claims))
    assert captured.value.category == category


@pytest.mark.asyncio
async def test_missing_required_claim_is_rejected(key_pair: tuple) -> None:
    private_key, public_key, _ = key_pair
    now = int(time.time())
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        private_key,
        algorithm="RS256",
        headers={"kid": KID, "typ": "at+jwt"},
    )
    with pytest.raises(AuthenticationFailure):
        await AccessTokenVerifier(auth_settings(), StaticCache(public_key)).verify(
            token
        )


@pytest.mark.parametrize(
    ("headers", "category"),
    [
        ({"alg": "HS256"}, "unexpected_algorithm"),
        ({"alg": "none"}, "unexpected_algorithm"),
        ({"typ": "JWT"}, "wrong_token_type"),
        ({"kid": ""}, "missing_key_id"),
    ],
)
@pytest.mark.asyncio
async def test_untrusted_header_cannot_change_verification_policy(
    key_pair: tuple,
    headers: dict[str, object],
    category: str,
) -> None:
    private_key, public_key, _ = key_pair
    token = access_token(private_key)
    parts = token.split(".")
    forged_headers = {"alg": "RS256", "kid": KID, "typ": "at+jwt", **headers}
    encoded = jwt.utils.base64url_encode(json.dumps(forged_headers).encode()).decode()
    forged = ".".join((encoded, parts[1], parts[2]))
    with pytest.raises(AuthenticationFailure) as captured:
        await AccessTokenVerifier(auth_settings(), StaticCache(public_key)).verify(
            forged
        )
    assert captured.value.category == category


@pytest.mark.asyncio
async def test_invalid_signature_and_malformed_token_are_rejected(
    key_pair: tuple,
) -> None:
    private_key, public_key, _ = key_pair
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = AccessTokenVerifier(auth_settings(), StaticCache(public_key))
    with pytest.raises(AuthenticationFailure):
        await verifier.verify(access_token(other_key))
    with pytest.raises(AuthenticationFailure) as captured:
        await verifier.verify("not-a-jwt")
    assert captured.value.category == "malformed_token"


@pytest.mark.asyncio
async def test_token_size_and_age_are_bounded(key_pair: tuple) -> None:
    private_key, public_key, _ = key_pair
    verifier = AccessTokenVerifier(
        auth_settings(auth_max_token_bytes=512, auth_max_token_age_seconds=60),
        StaticCache(public_key),
    )
    with pytest.raises(AuthenticationFailure) as captured:
        await verifier.verify(access_token(private_key, claims={"padding": "x" * 1000}))
    assert captured.value.category == "token_too_large"
    old = int(time.time()) - 61
    token = access_token(private_key, claims={"iat": old, "exp": old + 600})
    verifier = AccessTokenVerifier(
        auth_settings(auth_max_token_age_seconds=60), StaticCache(public_key)
    )
    with pytest.raises(AuthenticationFailure) as captured:
        await verifier.verify(token)
    assert captured.value.category == "token_too_old"


@pytest.mark.asyncio
async def test_bounded_clock_skew(key_pair: tuple) -> None:
    private_key, public_key, _ = key_pair
    verifier = AccessTokenVerifier(
        auth_settings(auth_clock_skew_seconds=30), StaticCache(public_key)
    )
    identity = await verifier.verify(
        access_token(private_key, claims={"nbf": int(time.time()) + 15})
    )
    assert identity.subject == "external-subject"


@pytest.mark.asyncio
async def test_unknown_kid_refreshes_at_most_once(key_pair: tuple) -> None:
    _, public_key, _ = key_pair
    cache = JWKSCache(auth_settings())
    cache._keys = {KID: public_key}
    cache._expires_at = monotonic_value = time.monotonic() + 60
    calls = 0

    async def refresh() -> None:
        nonlocal calls
        calls += 1
        cache._keys = {KID: public_key}
        cache._expires_at = monotonic_value

    cache._refresh = refresh  # type: ignore[method-assign]
    with pytest.raises(AuthenticationFailure):
        await cache.key("rotated-key")
    assert calls == 1


@pytest.mark.asyncio
async def test_legitimate_key_rotation_refreshes_once(key_pair: tuple) -> None:
    _, public_key, _ = key_pair
    cache = JWKSCache(auth_settings())
    cache._keys = {"old-key": public_key}
    cache._expires_at = time.monotonic() + 60
    calls = 0

    async def refresh() -> None:
        nonlocal calls
        calls += 1
        cache._keys = {KID: public_key}
        cache._expires_at = time.monotonic() + 60

    cache._refresh = refresh  # type: ignore[method-assign]
    assert await cache.key(KID) is public_key
    assert calls == 1


@pytest.mark.asyncio
async def test_expired_cache_fails_closed_when_refresh_is_unavailable(
    key_pair: tuple,
) -> None:
    _, public_key, _ = key_pair
    cache = JWKSCache(auth_settings())
    cache._keys = {KID: public_key}
    cache._expires_at = 0

    async def unavailable() -> None:
        raise AuthenticationFailure("jwks_unavailable")

    cache._refresh = unavailable  # type: ignore[method-assign]
    with pytest.raises(AuthenticationFailure) as captured:
        await cache.key(KID)
    assert captured.value.category == "jwks_unavailable"


def test_jwk_type_use_and_algorithm_are_allowlisted(key_pair: tuple) -> None:
    _, _, public_jwk = key_pair
    for changes in (
        {"kty": "oct"},
        {"use": "enc"},
        {"alg": "HS256"},
        {"key_ops": ["sign"]},
    ):
        assert JWKSCache._validate_key({**public_jwk, **changes}, "RS256") is None


@pytest.mark.asyncio
async def test_jwks_cache_hit_avoids_network(key_pair: tuple) -> None:
    _, public_key, _ = key_pair
    cache = JWKSCache(auth_settings())
    cache._keys = {KID: public_key}
    cache._expires_at = time.monotonic() + 60
    assert await cache.key(KID) is public_key


def test_role_permission_matrix_is_least_privilege() -> None:
    assert has_permission(CollectionRole.VIEWER, Permission.READ)
    assert not has_permission(CollectionRole.VIEWER, Permission.UPLOAD)
    assert has_permission(CollectionRole.EDITOR, Permission.UPLOAD)
    assert not has_permission(CollectionRole.EDITOR, Permission.MANAGE_COLLECTIONS)
    assert has_permission(CollectionRole.MANAGER, Permission.DELETE_DOCUMENT)
    assert not has_permission(MembershipRole.MEMBER, Permission.UPLOAD)
    assert has_permission(MembershipRole.ADMIN, Permission.MANAGE_COLLECTIONS)
    assert has_permission(MembershipRole.OWNER, Permission.MANAGE_MEMBERS)


def test_authentication_configuration_fails_closed() -> None:
    with pytest.raises(ValueError):
        Settings(app_env="production", auth_enabled=False)
    with pytest.raises(ValueError):
        Settings(app_env="production", auth_enabled=True)
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            auth_enabled=True,
            auth_issuer=ISSUER,
            auth_audience=AUDIENCE,
            auth_jwks_url=f"{ISSUER}/jwks",
            auth_allow_insecure_http=True,
        )
    with pytest.raises(ValueError):
        Settings(app_env="production", embedding_provider="fake", auth_enabled=True)
    with pytest.raises(ValueError):
        Settings(app_env="production", reranker_provider="fake", auth_enabled=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/auth/me"),
        ("GET", "/collections?tenant_id=00000000-0000-0000-0000-000000000001"),
        ("GET", "/processing-jobs/00000000-0000-0000-0000-000000000001"),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/keyword-search",
        ),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/semantic-search",
        ),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/hybrid-search",
        ),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/reranked-search",
        ),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/ask",
        ),
        (
            "POST",
            "/collections/00000000-0000-0000-0000-000000000001/documents",
        ),
    ],
)
async def test_protected_endpoint_families_require_bearer_authentication(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    monkeypatch.setattr("app.auth.get_settings", lambda: auth_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(
            method,
            path,
            json={"query": "synthetic"} if method == "POST" else None,
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


@pytest.mark.asyncio
async def test_malformed_authorization_scheme_returns_safe_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.auth.get_settings", lambda: auth_settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/auth/me", headers={"Authorization": "Basic not-a-bearer-token"}
        )
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication credentials are required"}
