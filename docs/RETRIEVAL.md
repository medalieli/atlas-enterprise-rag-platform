# Keyword, semantic, and hybrid retrieval

Milestone 7 adds PostgreSQL full-text keyword search and deterministic hybrid fusion while
preserving the Milestone 6 semantic endpoint. These endpoints return retrieved passages,
not answers, validated citations, probabilities, or confidence percentages.

## Full-text representation

Each `document_chunks` row has a stored generated `search_vector` column. PostgreSQL turns
stable section context and exact chunk content into searchable lexemes with
`to_tsvector('simple', ...)`; section terms receive weight `A` and content terms weight
`B`. IDs, timestamps, jobs, embedding metadata, and other unstable values are excluded.
The original `content` column is returned unchanged so source offsets remain traceable.

The explicit `simple` configuration is the current multilingual and identifier-oriented
default. It does not apply language-specific stemming, which is useful for mixed
English/French collections and exact enterprise identifiers such as `ENTREFUND30` or
`ACME-SLA-42`. Recall for inflected natural-language forms can be lower than with an
English or French dictionary. Language-specific vectors can be introduced later only
through a controlled schema and reindexing migration.

A `tsvector` is PostgreSQL's normalized searchable representation. A `tsquery` represents
the parsed user search. `ix_document_chunks_search_vector_gin` is a GIN index compatible
with the `@@` match operator. Keyword requests use
`websearch_to_tsquery('simple', :query)` rather than constructing raw `to_tsquery` syntax,
so ordinary text, quoted phrases, `OR`, negation, punctuation, and Unicode are parsed by
PostgreSQL with a bound user value. An empty/non-indexable query returns no results.

Keyword matches use `ts_rank_cd`; ties use chunk UUID for deterministic ordering. The
score is lexical relevance within this query and configuration. It is not comparable to
cosine similarity across retrieval methods.

## Secured candidate retrieval and fusion

Both branches constrain tenant, collection, available-document status, and current
embedding metadata inside their SQL queries. Candidates are never fused globally and
filtered afterward. Trusted-principal membership is checked before either query.

Hybrid retrieval reuses the semantic branch's pgvector strict iterative HNSW scan and its
already-scoped exact fallback. It embeds the query once, independently retrieves bounded
semantic and keyword candidates, and fuses them in Python. This avoids duplicating the
Milestone 6 approximate-search correctness logic.

Each branch retrieves:

```text
candidate_depth = min(4 * top_k, 200)
```

Reciprocal Rank Fusion uses `rrf_k = 60`:

```text
1 / (60 + semantic_rank) + 1 / (60 + keyword_rank)
```

A missing branch contributes zero. Duplicate chunk IDs merge into one result, and equal
RRF scores use chunk UUID as the stable tie-breaker. The RRF score is only a ranking value;
it is not a probability or confidence percentage. Responses expose component ranks and
raw component scores for debugging.

## API examples

Keyword search:

```http
POST /collections/33333333-3333-4333-8333-333333333333/keyword-search
Content-Type: application/json

{"query":"ENTREFUND30 OR \"enterprise refund policy\"","top_k":5}
```

Hybrid search:

```http
POST /collections/33333333-3333-4333-8333-333333333333/hybrid-search
Content-Type: application/json

{"query":"How can enterprise clients recover their purchase funds?","top_k":5}
```

The existing semantic route and response remain available at
`POST /collections/{collection_id}/semantic-search`. All modes accept query text up to
8,000 characters and `top_k` from 1 through 50. Keyword search does not require OpenAI.
Hybrid search never silently falls back to keyword-only: an embedding configuration,
quota, provider, or validation failure produces the same safe observable error class as
semantic search, and clients may explicitly choose keyword search.

Retrieval logs contain mode, candidate/result counts, and elapsed time, but never query or
document text, vectors, credentials, authorization headers, or raw provider responses.

## Migration and operations

Revision `e8f7a6b5c4d3` adds the stored generated column and GIN index. PostgreSQL computes
the generated value for existing rows during the migration, so no OpenAI call occurs and
embedding columns remain unchanged. New inserts and content/section updates maintain the
vector automatically.

The normal transactional migration is **not zero-downtime** on a large populated table.
Adding the stored generated column can rewrite the table, and ordinary GIN index creation
can block writes. Operators should estimate table size and build time, take a backup, and
use a maintenance window. A high-scale deployment should use a separately designed staged
rollout (for example, an application-maintained nullable vector, batched backfill,
validation, and `CREATE INDEX CONCURRENTLY` outside the normal transaction) rather than
pretending this migration is online. That alternate rollout is not part of Milestone 7.

## Evaluation and deferred work

Deterministic fixtures compare exact identifiers (keyword strength), paraphrased wording
(semantic strength), and passages supported by both channels (hybrid fusion). They also
exercise empty branches, stable ties, deduplication, depth bounds, and isolation. Tiny test
fixtures verify GIN/HNSW definitions and operator compatibility; they do not claim that
PostgreSQL's planner will choose either index at production scale.

Still deferred are reranking and advanced metadata filters, answer generation, validated
citations, authentication, conversation memory, lifecycle reindexing/versioning,
frontend highlighting, broad evaluation/observability, and deployment hardening.
