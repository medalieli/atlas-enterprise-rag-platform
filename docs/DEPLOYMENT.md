# Production deployment

The production overlay is provider-neutral. It does not prove a public deployment. No Git remote, registry, server, domain, DNS authority, or production OIDC client was configured at Milestone 15 implementation time.

## Required inputs

Provide a Linux container host or approved platform, a domain/hostname and DNS control, a real OAuth/OIDC client whose callback is `https://HOST/api/auth/callback`, permitted registry/deployment credentials, and TLS certificate automation or a mounted certificate/key. Prefer workload identity/OIDC over long-lived cloud keys. Set every `*_IMAGE` to an immutable digest reference, `RELEASE_REVISION` to the commit SHA, and `BUILD_DATE` to RFC 3339 UTC. The proxy is the only published service; never publish data or telemetry networks.

Create separate root-readable files outside the repository for the database URL, database password, OpenAI key, 32+ byte random session key, OIDC client secret, 32+ byte metrics token, and Grafana password. Compose mounts these files but does **not** encrypt them at rest. Use a platform secret manager where available and restrict file ownership/mode. Generate values with an OS CSPRNG; never paste them into shell history. Rotate one credential at a time, restart only consumers, verify, then revoke the old value. Revoke provider credentials immediately after suspected exposure.

Validate with `operations/verify-compose.ps1`, build/tag the exact revision, and run migrations once with `docker compose ... run --rm --no-deps api alembic upgrade head` before scaling API/worker. Confirm `current` and `check`, start, then perform authenticated synthetic smoke tests. Health endpoints check process/PostgreSQL/pgvector only and never call OpenAI.

Rollback application images with prior immutable references. Do not automatically downgrade schema. On a failed transactional migration, keep the old application running, inspect the revision/logs, correct and retry. Restore the coordinated pre-deployment backup into an isolated target if data changed incompatibly. Lifecycle downgrades may refuse when multiple versions exist; never force destructive rollback.

Set `PRODUCTION_HOSTNAME` to the single public hostname, without a scheme; unknown Host values are rejected. HSTS is emitted only by HTTPS. The proxy overwrites forwarding headers, limits uploads to 21 MiB, and applies bounded timeouts/connections/rates with `429` responses. Permanent provider quota remains a distinct application error. CSP retains only the tested Next.js `unsafe-inline` bootstrap allowance; `unsafe-eval` is prohibited and removing the final inline allowance requires a nonce/hash migration. PDF ranges and DOCX citation links pass through unchanged.

After deployment verify isolation, upload/ingestion, retrieval, grounded citations, conversations, lifecycle, telemetry, backup and a separate restore. Record a URL only after success. A public smoke may use minimal OpenAI calls and must record operation/model/token/latency totals without prompts or outputs.
