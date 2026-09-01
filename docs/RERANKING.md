# Metadata filtering and reranking

Milestone 8 adds explicit document metadata filters to every retrieval mode and a
local cross-encoder reranking endpoint. It does not generate answers or citations.

## Metadata upload

`POST /collections/{collection_id}/documents` remains multipart and accepts an
optional `metadata` JSON string alongside `file`:

```json
{
  "tags": ["enterprise", "refund"],
  "department": "legal",
  "document_type": "policy",
  "language": "en",
  "effective_date": "2026-01-01"
}
```

Tags and department are trimmed and case-folded; tags are deduplicated in first-seen
order. Document type is one of `policy`, `contract`, `faq`, `manual`, or `other`.
Language is a bounded language tag and effective date is an ISO calendar date.
Unknown fields, nested objects, invalid types and oversized values are rejected.
Metadata cannot set tenant, collection, ownership, storage path, or filename fields.
The current `documents` row is the immutable uploaded snapshot/version identity, so
its JSONB metadata remains traceable to every chunk created from that upload.

## Shared filter contract

Semantic, keyword, hybrid and reranked requests accept the same optional `filters`
object. Supported fields are `document_ids`, `content_types`, `filenames`,
`created_from`, `created_to`, `tags_any`, `tags_all`, `departments`,
`document_types`, `languages`, `effective_from`, and `effective_to`.

Different fields use AND semantics. Multiple values within an identity or scalar
field use OR semantics. `tags_any` requires at least one tag and `tags_all` requires
every tag. All date boundaries are inclusive. Null filters and empty lists add no
predicate. Lists, strings, serialized payloads and UUID/date formats are bounded and
validated. Arbitrary JSON paths and SQL fragments are not accepted.

Every predicate is applied inside both tenant-and-collection-scoped PostgreSQL
candidate queries, before branch limits, rank positions or RRF fusion. Authorization
continues to come only from the trusted principal. Filtering is never performed over
an unscoped Python candidate set.

## Storage and indexes

The existing non-null `documents.metadata` JSONB column is reused. The migration adds
object/size constraints, tenant/collection B-tree indexes for creation time, MIME type
and filename, a GIN index for tag existence, and expression indexes only for the
scalar filters actually exposed. Effective dates are normalized ISO strings; their
chronological lexical order permits an immutable matching expression index without
depending on PostgreSQL `DateStyle`.

PostgreSQL 17 GIN indexes efficiently support the JSONB tag operators used here.
Expression B-tree indexes support equality/range predicates for bounded scalar
metadata. On a large populated installation, normal transactional index creation can
take locks and is not zero-downtime. Operators should validate legacy JSON shapes,
backfill in controlled batches if needed, and schedule this migration or adapt the
index operations to a separately reviewed `CREATE INDEX CONCURRENTLY` procedure.

## Reranking pipeline

`POST /collections/{collection_id}/reranked-search` embeds the query once, retrieves
secured semantic and keyword candidates, combines them using the existing RRF
formula, and reranks at most 30 fused candidates. It returns at most `top_k`; `top_k`
remains 1–50 but cannot exceed the configured candidate pool.

The passage sent to the reranker is deterministic: stable section context followed
by exact chunk content. The returned content and source offsets are never rewritten.
Results expose the new final rank, opaque reranker relevance score, original hybrid
rank/RRF score, component ranks and channels, plus allowed document metadata. Neither
RRF nor cross-encoder scores are probabilities, confidence percentages, or claims of
factual correctness.

Production uses `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` at immutable revision
`1427fd652930e4ba29e8149678df786c240d8825`. The model declares Apache-2.0 and is
packaged as safetensors during Docker build. Runtime uses local files only,
`trust_remote_code=False`, and never downloads mutable model code. Each API process
loads and warms one model instance. CPU inference runs outside FastAPI's event loop,
with defaults of 8 items per model batch, 512 tokens per pair, 30 seconds timeout and
two bounded inference threads. Missing/corrupt startup assets fail startup; timeout,
provider failure, wrong score count, unknown IDs and non-finite scores are observable.
Search and answer requests then retain the already authorized deterministic fused
order, so the optional local reranker cannot turn otherwise usable evidence into an
outage.

Queries containing bounded enterprise control IDs (for example `SEC-028`) or exact
retrieval markers (for example `SECORION1042`) receive an additional scoped lookup.
It uses the same tenant, collection, active-version, lifecycle and metadata predicates
as normal retrieval. Every chunk from the matched source unit is inserted into the
bounded reranker pool, and the complete evidence group is preserved in answer context
even if repetitive passages receive a lower cross-encoder score. Explicit comparison
queries also preserve document diversity before remaining slots follow reranked order.

Safe structured logs contain only modes, counts, batch counts and component timing.
They exclude query text, document content, metadata values, vectors, secrets and
authorization headers.

## Deferred work

Milestone 9 answer generation, prompt construction and validated answer citations;
authentication/JWT; conversations; deletion/version-management workflows; frontend
work; broad Milestone 14 evaluation; and deployment hardening remain deferred.
