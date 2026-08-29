# Milestone 15 verification record

Verified 2026-08-28 on a Windows workstation using Docker Desktop/Linux containers, synthetic documents, a disposable RS256 issuer and fake model providers. These are local fixture observations, not production capacity, RPO or RTO guarantees. No OpenAI request was made.

The repository is **deployment-ready, not publicly deployed**. No external deployment was performed and no live URL exists. A public launch still needs an approved server, hostname/domain and DNS control, production OIDC client, registry/deployment authorization, TLS automation and production secret handling.

## Automated gates

- Backend: Ruff and compilation passed; 170/170 PostgreSQL/pgvector tests passed. Alembic upgraded a fresh pgvector database to `c3d4e5f6a7b8`, `current` and `check` passed, the final revision downgraded and re-upgraded, and the disposable database was removed.
- Frontend: ESLint, strict TypeScript and production build passed; 14/14 unit and 6/6 Playwright desktop/mobile tests passed. npm production audit found zero vulnerabilities.
- Deterministic evaluation: 14/14 cases passed, dataset SHA-256 `df919658e1d0f2b4ebaf3669d30c87bebeb68702a5ca37c58b9be907e0a8f0da`, zero provider calls. Frozen dependency validation passed. pip-audit found no known vulnerability after excluding the separately indexed CPU Torch wheel; Bandit found zero medium/high and seven reviewed low findings.
- Development and production Compose validation, Gitleaks (15 commits, no leaks), both Dockerfiles under Hadolint, and `git diff --check` passed.

## Final images, SBOMs and vulnerability decision

Images were rebuilt from digest-pinned Python 3.12.14 Debian trixie and Node 22 Alpine bases. The backend runtime removes Perl, pip and build/package-manager tools and contains the revision-pinned safetensors reranker. The frontend runtime removes npm/Corepack/Yarn. Syft 1.31.0 (`sha256:c15fa8...e5abb`) generated CycloneDX SBOMs. Trivy 0.65.0 (`sha256:a22415...2436`) used its database downloaded 2026-08-28 and scanned the application images themselves. Frontend: zero critical/high. Backend: zero critical, zero fixable high, eight Debian-vendor unfixed highs. Nothing was ignored in the recorded JSON report; CI separately fails fixed critical/high findings while this table remains the required review of unfixed findings.

| CVE | Package / installed version | Vendor severity / fix | Used or reachable | Exposure and controls | Decision |
|---|---|---|---|---|---|
| CVE-2026-41992 | gzip 1.13-1 | High; no Debian fixed version | Vulnerable multi-file LZW-then-LZH CLI path is not invoked; uploads accept PDF/DOCX only | Non-root, read-only, no capabilities, no shell/tool dispatch from document content | Accept until Debian publishes a fix; rescan each build |
| CVE-2026-54369 | libacl1 2.3.2-2+b1 | High; no Debian fixed version | App performs no pathname ACL operations and is not privileged | UID 10001, all capabilities dropped, fixed storage prefix | Privilege-escalation preconditions absent; accept vendor-deferred |
| CVE-2025-69720 | libncursesw6 6.5+20250216-2 | High; no Debian fixed version | Vulnerable `infocmp` command is never invoked | No user-controlled subprocess command, non-interactive runtime | Accept vendor-deferred |
| CVE-2025-69720 | libtinfo6 6.5+20250216-2 | High; no Debian fixed version | Same unreachable `infocmp` path | Same controls | Accept vendor-deferred |
| CVE-2025-69720 | ncurses-base 6.5+20250216-2 | High; no Debian fixed version | Same unreachable `infocmp` path | Same controls | Accept vendor-deferred |
| CVE-2025-69720 | ncurses-bin 6.5+20250216-2 | High; no Debian fixed version | Same unreachable `infocmp` path | Same controls | Accept vendor-deferred |
| CVE-2026-11822 | libsqlite3-0 3.46.1-7+deb13u1 | High; no Debian fixed version | App uses PostgreSQL and never opens uploaded SQLite or executes SQLite FTS5 | PDF/DOCX allowlist; parsers do not dispatch SQLite | Crafted-FTS5 precondition absent; accept vendor-deferred |
| CVE-2026-11824 | libsqlite3-0 3.46.1-7+deb13u1 | High; no Debian fixed version | Same unreachable SQLite FTS5 path | Same controls | Accept vendor-deferred |

Any future critical or fixed high fails release. A materially reachable vendor-deferred high also blocks release.

## Authenticated load observation

The test-only path is gated by `APP_ENV=test`; production rejects fake answer, embedding and reranking providers. A standards-compliant ephemeral RS256 issuer authenticated viewer/editor/admin principals. Synthetic upload and polling, keyword, semantic, hybrid and reranked search, `/ask`, conversation creation and follow-up, role denials, tenant isolation, concurrency and rate limiting were exercised without OpenAI.

Sixty requests at concurrency 10 completed at 59.72 requests/s with zero unexpected errors. Each operation had ten requests:

| Operation | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|
| keyword | 573.42 | 877.93 | 877.93 |
| semantic | 597.36 | 911.59 | 911.59 |
| hybrid | 606.88 | 931.65 | 931.65 |
| reranked | 664.67 | 947.19 | 947.19 |
| ask | 691.58 | 959.03 | 959.03 |
| conversation follow-up | 841.74 | 1001.56 | 1001.56 |

The proxy auth burst produced two 307 redirects and eight safe 429 responses across ten immediate requests. The worker was bounded at concurrency 2 and API and database pools remained within configured limits. CPU, peak RSS, PostgreSQL connection high-water and precise ingestion queue delay were not captured during this sample; configured limits are not reported as measured utilization. This is an explicit measurement limitation, not a capacity claim.

## Controlled failure matrix

All service failures used disposable fixtures, one dependency at a time.

| Failure | Expected | Observed |
|---|---|---|
| Redis down/restored | Reads remain ready; durable jobs recover after broker return | Readiness stayed 200; durable publication/reconciliation tests passed |
| PostgreSQL down/restored | Safe unready response, then recovery | 503 with no connection detail; returned to 200 |
| Source storage missing/transient | Terminal safe missing-object state / bounded retry | Both paths passed; no partial derived rows |
| OpenAI timeout, 5xx, temporary 429 | Bounded retry and safe terminal state | Retry classification/delay tests passed |
| OpenAI permanent quota | Never retry | One attempt, observable terminal failure |
| Reranker unavailable/timeout | Bounded safe provider error | Provider tests passed |
| Reranker invalid output | Reject invalid ranking | Validation passed; no unsafe fallback |
| Telemetry collector down/restored | Requests continue; exporter failure isolated | Observability tests passed and stack recovered healthy |
| Duplicate Celery delivery | Idempotent replay | Same job result; no duplicate chunks/embeddings |

API/worker log inspection found no authorization value, secret, source marker, vector, internal storage path or raw provider response.

## Hardened production-overlay smoke

Short-lived strong secrets, CA, TLS certificate and RS256 signing key were generated under ignored `.tmp/m15-prod` with a restrictive host ACL; values were never printed. All ten application/observability containers became healthy. Only Nginx published host ports 80/443. PostgreSQL, Redis, storage, API, worker, frontend and telemetry had no published ports.

The proxy redirected HTTP with 308, validated the local CA over HTTPS, rejected an unknown Host with 421, and emitted HSTS, restrictive CSP (no `unsafe-eval`), frame, MIME, referrer, permissions and cross-origin isolation headers. OIDC authorization-code + PKCE reached `/chat`; Secure session/CSRF cookies were set; missing CSRF returned 403; logout returned 200 and removed the session. Production rejected missing/weak security configuration. All application containers ran non-root with read-only roots, explicit bounded tmpfs/volumes, all capabilities dropped, `no-new-privileges`, init, PID/CPU/memory/nofile limits, health checks, restart policies and stop timeouts. A controlled proxy restart retained database state and returned healthy. No real-provider upload was repeated: Milestone 14 already verified it, while authenticated fake-provider upload/ingestion was verified in the isolated test-only stack.

## OWASP ZAP

ZAP 2.17.0 was pinned to `sha256:781a2b...081ef`. Its Java trust store imported only the ephemeral local CA; TLS verification was not disabled. The baseline scanned 19 URLs on the local hardened endpoint: 0 failures, 61 passing rules, six warnings.

- Public login/session pages are intentionally cacheable and non-sensitive; no authenticated response was cached.
- Next.js 307 routes omit a content type and non-storable redirects are expected protocol behavior.
- `unsafe-inline` remains for the current Next.js bootstrap. `unsafe-eval` was removed; nonce/hash CSP migration remains defense in depth.
- The login redirect was correctly identified as session management.
- The reported COEP warning was remediated with `require-corp` after the scan; direct header and application smoke passed after restart.

## Backup and isolated restore

`pg_dump` custom format was 368,834 bytes; source objects were 1,619,855 bytes across 51 files. Backup took 1.808 s and restore 3.822 s. The disposable restore contained 27 tenants, 39 collections, 48 documents, versions and active generations, 52 chunks/embeddings, 9 conversations and 12 citations. Object manifest hashes, lifecycle/tombstone state and tenant keys matched. Authorized fake-provider retrieval/grounded-answer behavior was separately verified against the same fixture model and isolation assertions. The disposable target was removed; the working database was never overwritten.

Residual risks are the vendor-deferred unreachable image findings, inline CSP bootstrap allowance, local-only performance sample, untested public-platform integration and normal third-party provider availability/cost. These are limitations, not unsupported production guarantees.

## Post-v1 enterprise verification

The enterprise upgrade is verified separately from the completed 15-milestone
roadmap. The final local run passed 187 backend tests against PostgreSQL/pgvector,
19 frontend unit tests, and eight Playwright desktop/mobile scenarios. Ruff, Python
compilation, ESLint, strict TypeScript, the production frontend build, frozen locks,
Compose validation, and a 14-case deterministic evaluation (zero provider calls)
passed. Revision `d4e5f6a7b8c9` passed current/check, downgrade, upgrade, and repeated
upgrade on the disposable production-like database.

Both final application images built and all ten hardened production-overlay services
became healthy. Only the HTTPS proxy published ports; ephemeral RS256 OIDC login with
PKCE reached `/chat`, the BFF resolved the synthetic owner, the session cookie was
Secure/HttpOnly/SameSite, CSRF-less logout was rejected, and CSRF-protected logout
succeeded. Trivy 0.65.0 with its 2026-08-29 database reported zero fixable high or
critical OS/application findings in both images. NPM audit reported zero production
dependency findings. Bandit reported zero medium/high findings and seven low
heuristics (three deliberate durable-queue recovery catches, a fixed-argument Git
metadata subprocess, and a verification-only assert). Gitleaks' history scan retained
one previously documented false positive: an immutable image digest in the Milestone
15 smoke script, not a credential; the feature introduced no secret. No paid OpenAI
call or public deployment was performed.
