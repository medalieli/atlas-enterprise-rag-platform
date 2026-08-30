# Authentication and tenant authorization

Unauthenticated application requests redirect to `/login`, preserving a safe
relative destination. Authenticated visits to `/login` enter Atlas and logout
returns to the login experience. Atlas never receives or stores passwords; the
external OIDC provider owns credentials, reset, and MFA. PKCE, state validation,
trusted callback origins, HTTP-only session cookies, and mutation CSRF checks remain
mandatory.

Milestone 10 treats FastAPI as an OAuth 2.0 protected resource. The API validates
access tokens issued by a configured external OAuth/OIDC authorization server; it
does not register passwords, authenticate credentials, issue tokens, store refresh
tokens or implement an authorization server. Browser Authorization Code with PKCE
and token storage remain frontend work.

## Access-token policy

Business endpoints accept a token only as `Authorization: Bearer <ACCESS_TOKEN>`.
Liveness, readiness, the safe root response and the currently enabled OpenAPI pages
remain public. All collection, document, processing-job, retrieval, answer and
identity endpoints require authentication.

The verifier uses locked PyJWT and cryptography dependencies. It accepts only the
configured asymmetric algorithm (`RS256` by default), exact issuer and audience,
non-empty subject, `exp`, bounded `iat`, optional `nbf`, expected `typ=at+jwt` and
the configured scopes. It rejects `none`, HMAC/asymmetric confusion, ID-token style
`typ`, oversized tokens and missing/unknown key IDs. Token-controlled `jku`, `x5u`
and claim URLs are ignored; signing keys come only from `AUTH_JWKS_URL`.

JWKS requests have bounded timeout, response size, redirects, key count and cache
lifetime. RSA signing keys must be compatible with the configured algorithm and
may declare only signing/verification use. Cached keys avoid per-request network
calls. An unknown `kid` causes at most one refresh for rotation. After cache expiry,
an unavailable issuer fails closed; readiness does not call the issuer.

Production requires HTTPS issuer and JWKS URLs. Plain HTTP is accepted only when
`AUTH_ALLOW_INSECURE_HTTP=true` under `APP_ENV=development` or `test`. Authentication
cannot be disabled outside those environments.

Access tokens are signed, not encrypted. Providers must not place secrets or
sensitive profile data in claims. Bearer tokens must be protected with TLS and safe
client-side storage. Offline JWT validation may not observe provider revocation
before token expiry; no application token blacklist is implemented.

## Internal principals and memberships

The authoritative identity key is the unique `(issuer, subject)` pair stored on the
internal `users` principal row. Email is optional profile data and is never used for
authorization. A cryptographically valid but unknown or disabled principal receives
`401` and is not automatically provisioned.

Tenant access comes only from an enabled database membership. Token claims, request
bodies, metadata and tenant selector parameters cannot create membership. Users with
multiple memberships must explicitly select a tenant for collection listing or
creation; resource-ID endpoints derive the tenant by joining the resource to the
principal's enabled membership.

Database membership is the application-authorization source of truth. Every request
rechecks active membership and collection grants, so suspension, revocation and
role changes take effect on the next request rather than waiting for JWT expiry.
Organization roles are `owner`, `admin` and deny-by-default `member`. Collection
grants are `manager`, `editor` and `viewer`; owners/admins implicitly manage every
collection. The exact matrices and invitation flow are documented in
[`POST_V1_ENTERPRISE_UPGRADE.md`](POST_V1_ENTERPRISE_UPGRADE.md).

Atlas never creates or stores passwords and provides no password-reset or MFA
workflow. Those controls remain exclusively with the configured OIDC provider.

Invitation links land on a public, non-enumerating page. The one-time capability is
carried in a URL fragment, immediately exchanged for a 15-minute encrypted,
HttpOnly continuation cookie, and removed from browser-visible history before OIDC
starts. After Authorization Code + PKCE completes, the BFF returns to that landing
page. Atlas still requires the configured issuer, an exact canonical email match,
and `email_verified=true`; a wrong signed-in identity receives sign-out-and-retry
guidance without disclosure of the invited address. The same accepted subject may
replay acceptance idempotently, while every other replay remains unavailable.

For local verification only, start `operations/ephemeral_oidc.py` with
`--interactive-identities`. Its authorization page can deterministically select the
synthetic owner, admin, editor, or invitee profiles. Create the invitation for the
selected invitee profile, then choose **Invitee** in a completely new browser
context. These immutable synthetic subjects are not production credentials, use no
passwords, and are unavailable unless the test-only utility is started explicitly.

Permissions are centralized as `tenant:read`, `document:upload` and
`collection:manage`. Unknown/missing resources and cross-tenant resources return the
same `404`. Valid identities lacking a general role permission receive `403`.
Missing, malformed, expired or invalid authentication receives `401` with a Bearer
`WWW-Authenticate` challenge.

`GET /auth/me` returns only the internal principal UUID and enabled tenant
memberships with roles/permissions. It never returns claims, subjects, email or the
token.

## Explicit provisioning

An administrator binds an external identity to an existing tenant explicitly:

```powershell
cd backend
uv run python -m app.bootstrap_identity `
  --issuer "https://identity.example.com/" `
  --subject "provider-stable-subject" `
  --tenant-id "<TENANT_UUID>" `
  --role viewer
```

The command is idempotent for the same issuer, subject and tenant. It creates no
tenant, password, token, administrator or owner implicitly. Re-running it can
intentionally set the requested role and re-enable the binding.

## Configuration

Set the non-secret `AUTH_*` values documented in `.env.example`. Provider metadata
discovery is not used: issuer and JWKS URL are configured independently and the
issuer claim must match exactly. This prevents tokens from selecting key locations.

Example authenticated request:

```http
POST /collections/<COLLECTION_UUID>/keyword-search
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{"query":"ENTREFUND30","top_k":5}
```

## Isolation and background processing

Application queries join enabled memberships before tenant resources are returned
or mutated. Retrieval filters tenant and collection inside both semantic and keyword
branches, and citation resolution rechecks the same scope. Workers receive only
server-created tenant, document and job UUIDs; bearer tokens are never queued.
Processing jobs retain the authenticated internal principal UUID for audit and
revalidate the persisted tenant/document/job relationship before mutation.

PostgreSQL Row-Level Security is not enabled in this milestone. Isolation is
application-enforced and integration-tested. Superficial RLS would not add a real
boundary while the application role can bypass it; a separate restricted database
role and operational design are prerequisites for genuine database-enforced RLS.

## Migration operations

Revision `a1b2c3d4e5f6` adds issuer/subject and enabled-state columns, converts the
membership enum to viewer/editor/admin, and adds the job audit foreign key and
indexes. Existing users receive deterministic legacy issuer/subject values and keep
their memberships as viewers. Enum replacement and table/index changes can acquire
locks on populated installations. Schedule the transactional migration in a
maintenance window and measure lock duration; it is not claimed to be zero-downtime.

Safe logs may contain internal UUIDs, permission names, cache outcomes and error
categories. Tokens, headers, claims, issuer subjects, emails, key bodies and signing
material are never logged.
