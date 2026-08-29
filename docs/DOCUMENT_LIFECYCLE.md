# Document lifecycle

The frontend exposes Milestone 12 details/history, replace, reindex, and hard
delete without introducing another lifecycle. Viewers cannot mutate; editors can
replace/reindex; managers and organization owner/admin roles can also delete. Hard
deletion requires typing `DELETE`, removes active retrieval content, and retains
redacted citation tombstones and immutable audit evidence. Archive remains
unavailable because the existing model has no recoverable archive transition.

Milestone 12 completes the document lifecycle architecture. Before this milestone,
`documents` combined logical identity and source-snapshot state, chunks were replaced
in place, and `conversation_citations.document_version_id` was only a compatibility
value equal to the document ID. It was not backed by a document-version foreign key.

## Identity and state

The authoritative relationship is:

`document -> active source version -> active index generation -> source units/chunks`

- A `document` is a tenant/collection-scoped logical identity. Its lifecycle is
  `pending -> processing -> available -> deleting -> deleted`; failure before an
  initial activation may produce `failed`. `deleting` and `deleted` cannot return to
  a readable state.
- A `document_version` is an immutable uploaded PDF/DOCX snapshot. Its source key,
  checksum, safe filename, type, byte size, and validated metadata are authoritative
  here. States are `pending -> processing -> ready -> active -> superseded`, with
  `failed` as a terminal candidate failure.
- A `document_index_generation` is an immutable processing result for one source
  version. It records parser, cleaner, chunker, embedding, and text-search settings
  plus a deterministic fingerprint. Reindexing creates a generation, not a source
  version. Generation states follow the version candidate states.

Initial migration rows deliberately use the existing document UUID for version 1.
This converts existing compatibility citation values into real version identities.
Every existing chunk/source unit is attached to generation 1. Incomplete legacy
documents are not made active by the backfill.

## Replacement and reindexing

An editor or admin creates a replacement with
`POST /collections/{collection_id}/documents/{document_id}/versions` and an
`Idempotency-Key`. Identical source bytes return `409` and direct the caller to
reindex. Version numbers are allocated while the logical document row is locked.
Parsing and provider calls occur without that lock. The prior active version remains
searchable until a short activation transaction rechecks document state and switches
the pointer.

An editor or admin requests reindexing with
`POST /collections/{collection_id}/documents/{document_id}/reindex`. The immutable
source object is reused. A separate candidate generation is built while the current
generation remains active, then `document_versions.active_generation_id` switches
atomically. This application operation never executes PostgreSQL `REINDEX INDEX`.

Committed queued jobs are durable even if broker publication fails. Operators can
run `uv run python -m app.job_reconciliation` to republish a bounded batch of stale
queued/retrying jobs. Worker arguments contain only tenant, document, and job UUIDs;
workers reload and validate version/generation state. Duplicate delivery is safe.

## Deletion and citations

Only admins may call `DELETE /collections/{collection_id}/documents/{document_id}`.
The transaction creates/reuses one deletion job and marks the document `deleting`,
which excludes it immediately from retrieval and blocks activation. The worker
deletes database-resolved source keys one at a time; missing objects are success.
Storage failure leaves the document unavailable and the job retryable.

Before derived rows are purged, historical conversation citations are converted to
`deleted` tombstones. Exact excerpts, metadata, location, and all document/version/
generation/chunk foreign keys are cleared. The logical document tombstone contains
no private snapshot data. Historical assistant message text remains until a future
conversation-deletion feature exists; document deletion therefore cannot erase facts
already copied into answer prose.

Superseded (not deleted) versions and generations remain immutable and resolvable for
historical citations but are excluded from new retrieval by SQL active-pointer joins.
Individual version deletion and rollback are deferred because they are not Milestone
12 roadmap acceptance criteria.

## Authorization

| Operation | Viewer | Editor | Admin |
| --- | --- | --- | --- |
| Inspect document/versions | Yes | Yes | Yes |
| Upload replacement | No | Yes | Yes |
| Request reindex | No | Yes | Yes |
| Delete document | No | No | Yes |

Every route derives tenant scope from enabled membership and returns safe `404` for a
cross-tenant or cross-collection identity. Clients never supply storage keys.

## Operations and migration

The migration performs table creation, populated-data backfill, and constraint/index
changes in one transactional migration. It takes schema and row locks and is not
claimed to be zero downtime. Schedule it for a maintenance window on populated
deployments. Downgrade is supported only while every document still has one version
and one generation; it refuses to discard multi-version history.

Ordinary lifecycle inserts/deletes update PostgreSQL GIN and pgvector HNSW indexes
normally. High-volume deletion can create table/index bloat. Run measured operational
`VACUUM` as appropriate; if measurement justifies it, use maintenance-time
`REINDEX INDEX CONCURRENTLY`. Neither action runs synchronously per document.

Deferred work: Milestone 13 frontend lifecycle UI and drag-and-drop; conversation
deletion/sharing; Milestone 14 broad evaluation dashboards; Milestone 15 backup,
multi-region storage, and deployment hardening; agents, tools, and external actions.
