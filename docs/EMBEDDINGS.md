# Embeddings and semantic vector retrieval

Milestone 6 represents each deterministic chunk as a numeric vector whose nearby vectors
are expected to have related meaning. Production uses OpenAI
`text-embedding-3-small`, 1,536 dimensions, and float encoding. Automated tests inject a
deterministic fake and never call OpenAI.

## Document and query flows

After parsing and chunking, `embedding-input-v1` prepends stable DOCX section context when
available and preserves exact chunk content. It excludes IDs, timestamps, and job data.
SHA-256 fingerprints cover the content hash, input version, model, and dimensions. Inputs
are token-counted and batched by item count and aggregate tokens without changing order.

OpenAI calls occur outside database transactions. Response indexes, count, dimension, and
values are validated; NaN, infinity, and all-zero vectors are rejected. A short transaction
publishes source units, chunks, complete embedding metadata, document availability, and job
success together. Permanent errors fail visibly without partial publication. Transient
timeouts, connection errors, rate limits, and server errors use bounded Celery retries.
SDK retries default to zero so retry loops do not multiply.

A duplicate completed task exits before provider construction and makes zero calls. An API
request may have succeeded immediately before a worker crash; since OpenAI and PostgreSQL
cannot share a transaction, redelivery can repeat that external call before commit.
Fingerprints prevent duplicate rows and support controlled re-embedding.

`POST /collections/{collection_id}/semantic-search` accepts a nonblank query and `top_k`
from 1 through 50 (default 10). Trusted-principal membership establishes tenant scope.
The API embeds the query, searches only available documents with matching non-null vectors,
and reports similarity as `1 - cosine_distance`. Results order by distance then chunk UUID.

The partial HNSW index uses `vector_cosine_ops`. Because pgvector 0.8.x applies filters
after approximate scanning, queries enable strict iterative scans. If a bounded scan cannot
fill the authorized result count, an exact scan repeats the same tenant and collection
predicates. Authorization is never widened for recall.

```http
POST /collections/11111111-1111-1111-1111-111111111111/semantic-search
Content-Type: application/json

{"query":"Can enterprise customers get their money back?","top_k":5}
```

```json
{"results":[{"rank":1,"similarity_score":0.91,"chunk_id":"...","document_id":"...","document_name":"policy.pdf","content":"...","page_number":2,"section_path":null,"start_offset":120,"end_offset":310}]}
```

These are retrieval results, not answers or validated citations.

## Configuration, backfill, privacy, and limits

`OPENAI_API_KEY` may be empty at startup; an OpenAI-backed operation then returns an
observable configuration failure. API and worker receive it only at runtime. Settings also
cover provider, model, dimensions, batch size, timeout, provider retry count, per-input
tokens, and per-request aggregate tokens; see `.env.example`.

Backfill nullable/stale chunks idempotently one document at a time:

```powershell
Set-Location backend
uv run python scripts/embed_pending.py <tenant-uuid> <document-uuid>
```

Changing model or input version changes fingerprints and requires controlled re-embedding.
The schema uses `vector(1536)`, so dimension changes require a migration plus full
re-embedding; settings reject a runtime mismatch.

Embedding sends chunk/query text to the provider and incurs usage cost. Operators must
assess data classification, retention, regional processing, and provider terms. Text,
vectors, keys, and authorization headers are never logged.

Semantic similarity is not factual verification. Full-text/hybrid search, reranking,
answers, validated citations, authentication, conversation memory, lifecycle reindexing,
frontend work, evaluation/observability expansion, and deployment hardening remain
Milestones 7 through 15.
