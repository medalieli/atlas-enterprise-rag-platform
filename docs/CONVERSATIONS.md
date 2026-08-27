# Conversation history and follow-up rewriting

Conversation state is authoritative in PostgreSQL and is scoped to the authenticated
creator, tenant, and collection. The API does not use OpenAI Conversations or
`previous_response_id`; every Responses API request sets `store=false`. This prevents
application-state storage by Responses, but is not equivalent to organization-level
Zero Data Retention.

## API

- `POST /collections/{collection_id}/conversations` creates an owned conversation.
- `GET /collections/{collection_id}/conversations` lists owned conversations using a
  stable `(created_at, id)` cursor.
- `GET /collections/{collection_id}/conversations/{conversation_id}` returns one.
- `GET .../{conversation_id}/messages` uses a stable sequence-number cursor.
- `POST .../{conversation_id}/messages` creates a turn and requires an
  `Idempotency-Key` header.

The turn body contains `query`, `top_k`, and the same typed metadata `filters` used by
stateless search and `/ask`. Reusing a key with the identical body returns the stored
validated result without provider work; a different body or concurrent active turn
returns `409`. Provider failures leave a failed turn, never a fabricated assistant
answer. A retry uses a new key.

## Bounded history and rewriting

The default history window contains at most six turns, twelve complete messages,
4,000 estimated tokens, and 16,000 characters. Pending and failed turns, document
chunks, citation excerpts, and prompts are excluded. Selected history is ordered oldest
to newest. The first turn bypasses rewriting. Later turns use configurable
`gpt-5.6-luna`, low reasoning, strict structured output, no tools, bounded retry and
timeout, and `store=false`.

The rewriter returns `standalone`, `rewritten`, or `clarification_required`. History is
untrusted context and previous answers are never evidence. A clarification skips
embedding, retrieval, reranking, and Terra generation. Once a standalone query exists,
the current authenticated, metadata-filtered hybrid/reranked pipeline runs and
`gpt-5.6-terra` generates an answer grounded only in current-turn chunks. Citations are
validated against PostgreSQL again and persisted only with the completed assistant
message.

Cross-tenant, cross-collection, and cross-user conversation identifiers return the same
safe `404`. Conversation content, queries, rewritten queries, source content, prompts,
tokens, and provider responses must not enter logs.

Deferred: deletion and retention automation, sharing, generated titles, history
summarization, streaming/WebSockets, frontend chat, document lifecycle, broad
evaluation dashboards, deployment hardening, and agents/tools.
