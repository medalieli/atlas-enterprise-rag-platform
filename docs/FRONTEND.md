# Production frontend

Milestone 13 adds a strict-TypeScript Next.js App Router application in
`frontend/`. It is an authenticated enterprise workspace, not a public marketing
site. The primary routes are `/chat` and `/documents`; `/`, `/session-expired` and
`/unauthorized` are intentionally public states.

## Identity provider and BFF

The browser starts Authorization Code flow with PKCE at `/api/auth/login`. The
callback exchanges the code server-side and stores access/refresh tokens only in an
encrypted `Secure`, `HttpOnly`, `SameSite=Lax` session cookie. Browser JavaScript
never receives either token. A separate `SameSite=Strict` double-submit CSRF value
protects logout and every state-changing `/api/backend/*` request. The BFF checks
the session on every operation, refreshes near-expiry access tokens server-side,
allowlists relative return paths, forwards only required headers, disables caching,
and sends the bearer token to FastAPI over the private service URL.

Configure these server-only values (none use `NEXT_PUBLIC_*`):

- `APP_ENV`: required explicitly by the container entrypoint. Use `development` or
  `test` only for their corresponding local modes; missing, unknown and production
  values fail secure in application cookie handling. The production overlay sets
  `production` and enforces HTTPS, strong session configuration and complete OIDC
  endpoints before startup.
- `SESSION_SECRET`: at least 32 random characters; use secret management outside development.
- `OIDC_AUTHORIZATION_URL` and `OIDC_TOKEN_URL`: external provider endpoints.
- `APP_BASE_URL`: the externally reachable frontend origin used for OAuth callbacks
  (for example, `http://localhost:3000` locally and the HTTPS application origin in production).
- `OIDC_CLIENT_ID` and optional confidential `OIDC_CLIENT_SECRET`.
- `OIDC_SCOPES`: defaults to `openid profile offline_access rag:access`.
- `API_INTERNAL_URL`: FastAPI service base URL; Compose uses `http://api:8000`.

The provider must allow the callback URL
`http://localhost:3000/api/auth/callback` for local development (HTTPS in
production). FastAPI remains the authorization authority. UI visibility derives
from `/auth/me`, but every BFF request is revalidated by authenticated FastAPI
collection/tenant queries.

The optimized container keeps `NODE_ENV=production` in every deployment. `APP_ENV`
separately controls deployment security so explicit local HTTP development can omit
the cookie `Secure` attribute while production always uses the `__Host-rag_session`
Secure cookie. The repository's `operations/ephemeral_oidc.py` issuer is only a
synthetic verification utility, is not copied into either application image, and is
not a production identity provider; production requires configured external OIDC.

## Local development

```powershell
Set-Location frontend
npm ci
npm run dev
```

The lockfile pins Next.js 16.3.3, React 19.2.8, TypeScript 5.9.3 and all transitive
packages. The app expects FastAPI at the configured `API_INTERNAL_URL`.

```powershell
docker compose up --build -d
docker compose ps
```

The frontend is exposed at <http://localhost:3000> and has a real Compose health
check. The source preview endpoint resolves a database-authorized immutable version
and serves it inline with `private, no-store`; PDF citations open the exact one-based
page through the browser PDF viewer, while DOCX citations use their precise section
and bounded excerpt. Character offsets are never presented as fake visual highlights.

## Roles and workflows

- Viewers can select authorized collections, inspect documents and versions, use
  conversations, and inspect citations.
- Editors additionally upload PDF/DOCX sources, replace versions, and reindex.
- Admins additionally create collections and explicitly confirm deletion.

Candidate versions and generations retain processing status until backend activation;
the UI never promotes them optimistically. Job polling is bounded to 60 attempts,
cleans up timers on unmount, and leaves the prior active source visible after a safe
failure. Conversation IDs are retained per collection in session storage (never token
material), messages use UUID idempotency keys, and only the active turn interaction is
disabled while processing.

## Verification

```powershell
Set-Location frontend
npm run typecheck
npm run lint
npm test
npm run build
npx playwright test
```

Vitest uses deterministic mocked responses and never calls OpenAI. Playwright covers
desktop and mobile login/session states, document lifecycle, ingestion, chat,
follow-up answers, citations, navigation and automated axe accessibility checks.
Synthetic screenshots are written under ignored `frontend/qa/` for local visual QA.

The post-v1 enterprise upgrade adds responsive Members, Invitations, Audit Activity,
and Product Analytics pages for owners/admins. Collection roles hide unavailable
upload, lifecycle, and grant controls for usability, while the API remains
authoritative. Eligible assistant answers expose accessible helpful/not-helpful
controls. Greeting-only turns and empty collections render deterministic guidance
without citations or provider calls. See `POST_V1_ENTERPRISE_UPGRADE.md`.
