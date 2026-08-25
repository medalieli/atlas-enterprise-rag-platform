# Milestone 4 ingestion

## Request flow

`POST /collections/{collection_id}/documents` accepts one multipart `file`. The API gets
the tenant and user from a server-owned `TrustedPrincipal`, verifies a matching database
membership and tenant-scoped collection, streams the file to storage, validates it, and
creates the document and processing-job rows. Only after commit does it publish the three
UUID identifiers to Redis. A successful request returns `202` with safe identifiers,
filename, and `queued` status.

Authentication arrives in Milestone 10. Until then tests override the principal dependency.
Docker can use `DEVELOPMENT_TENANT_ID` and `DEVELOPMENT_USER_ID` only when `APP_ENV` is
exactly `development`; empty values disable uploads. This is not an HTTP identity header.

## Storage and validation

`DocumentStorage` separates upload business logic from the local implementation so an
S3-compatible backend can replace it later. Docker mounts the persistent
`document_storage` volume into both API and worker. Server-generated tenant/document UUID
keys are resolved beneath the configured root. Writes use an exclusive partial file,
streamed 64 KiB chunks, an enforced 20 MiB default limit, SHA-256 calculation, `fsync`, and
atomic replacement. Failures remove partial/final files.

Only `.pdf` with `application/pdf` and `.docx` with the standard OOXML MIME type are
accepted. PDFs require `%PDF-`. DOCX files must be readable ZIP archives containing
`[Content_Types].xml` and `word/document.xml`; expanded content defaults to at most 100 MiB
and extreme compression ratios are rejected. File contents remain untrusted and are not
parsed in this milestone.

## Worker and observable states

Redis is a private Compose-only broker. Messages contain tenant, document, and job UUIDs,
never bytes or paths. PostgreSQL is authoritative for `queued`, `running`, `retrying`,
`succeeded`, and `failed`. `GET /processing-jobs/{job_id}` is tenant-scoped.

The late-acknowledged task locks its job row, treats succeeded and currently running jobs
as no-ops, verifies the stored file and checksum, and marks it succeeded. Missing or
changed files fail permanently. Storage I/O errors retry at most three times with bounded
exponential delay; Celery adds broker retry jitter. Attempts and timestamps are persisted.

There is no distributed transaction spanning PostgreSQL, storage, and Redis. If database
creation fails, storage is removed. If publishing fails, the just-created rows and file are
removed and the API returns `503`. A process crash in the narrow interval after broker
acceptance but before the HTTP response can still leave accepted work whose client did not
receive its IDs; an outbox table is the future production solution.

## Operations

```powershell
docker compose config
docker compose up --build -d
docker compose run --rm api uv run alembic upgrade head
docker compose exec worker uv run --no-sync celery -A app.worker:celery_app inspect ping
docker compose ps
```

Do not use `docker compose down -v`; that removes database and document volumes.
