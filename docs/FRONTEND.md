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

Milestone 14 evaluation/observability and Milestone 15 deployment hardening remain
explicitly deferred.
