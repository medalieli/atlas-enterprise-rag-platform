# Grounded answers and validated citations

Milestone 9 adds `POST /collections/{collection_id}/ask`. The endpoint uses the
existing trusted principal and collection membership checks, applies the shared
metadata filters inside semantic and keyword retrieval, performs RRF and local
cross-encoder reranking, then sends only bounded selected chunks to OpenAI.

## Deterministic context

Each complete retrieved chunk is one citable unit. Its stable source identifier is
`src_` followed by the immutable chunk UUID without separators; filenames are never
identifiers. Candidates retain reranked order, duplicate chunk IDs are removed, and
the builder includes complete chunks only while all configured limits hold:

- 8 context chunks by default (maximum configurable value 20);
- 12,000 context tokens;
- 48,000 context characters;
- 2,000 maximum generated tokens.

The system instruction, employee question and source container are separate. Source
blocks include a source ID, safe filename, readable page/section and exact chunk
text. Uploaded content is explicitly untrusted data: commands inside documents
cannot override the grounding instruction. Included/excluded counts are observable,
but text is never logged. No candidates means an immediate `insufficient_context`
response and no generation call.

## Generation provider

Production uses the OpenAI Responses API with native Pydantic Structured Outputs:

- configured model `gpt-5.6-terra` (the API currently exposes no distinct immutable
  snapshot identifier, so none is invented);
- reasoning effort `low`, standard request processing and medium verbosity;
- `store=false` explicitly;
- no tools, web search, file search, conversation or `previous_response_id`;
- 45-second total generation timeout, one bounded retry and two concurrent calls.

The OpenAI Python SDK is locked by `uv.lock`. The provider records the configured
model and the actual model returned by the API, plus aggregate input/output token
usage. Temporary network/server errors and genuine temporary rate limits can retry
once. Permanent quota, authentication, permission, bad request, refusal, incomplete
or malformed output fails safely with HTTP 503. The SDK owns no hidden retries.

`store=false` means the Responses API object is not stored for later application
retrieval. It does not by itself assert or enable organization-level Zero Data
Retention; retention eligibility and controls remain an OpenAI organization setting.

## Structured output and validation

The model returns only a strict status, bounded claims with supplied source IDs, and
an optional insufficient-context reason. Extra properties are forbidden. The server
rejects unknown IDs, IDs absent from this request, duplicates within a claim,
uncited factual claims, excessive claims/citations, invalid status combinations and
invalid usage values. `conflicting_sources` must reference at least two distinct
sources; `insufficient_context` must contain no claims or citations.

After structural validation, the server re-queries PostgreSQL with tenant,
collection and available-document constraints. It verifies the chunk, document
snapshot/version, source unit, exact text, page/section and offsets still match the
context. The model never supplies authoritative UUIDs, filenames or source locations.
Citation numbers are assigned in first-use order, claim markers such as `[1]` are
rendered by the server, and response citations contain only allowed metadata and the
exact bounded chunk. Invalid output is never partially displayed.

In the current schema, each `documents` row is the immutable uploaded snapshot and
therefore serves as the document-version identity; `document_version_id` equals that
snapshot's document ID. A separate version lineage is deferred to Milestone 12.

## Privacy, security and observability

Safe logs contain a tenant-safe correlation digest, model, counts, aggregate token
usage and retrieval/generation/total latency. They exclude questions, answers,
source text, prompts, metadata values, vectors, secrets, headers and raw provider
responses. API readiness warms only the local reranker and performs no billed call.
Authorization always comes from the trusted principal; request filters cannot set
tenant or collection scope.

## Deferred work

JWT authentication and comprehensive tenant management, conversation history,
follow-up rewriting, deletion/version lineage workflows, Next.js UI, PDF highlighting,
broad Milestone 14 evaluation, deployment hardening, agents, external tools, LangGraph
and external actions remain deferred.
