# Milestone 12 lifecycle evaluation

The reproducible authenticated evaluation is
`backend/scripts/live_m12_lifecycle_smoke.py`. It creates an isolated Compose
project and volumes, migrates an empty PostgreSQL/pgvector database, generates an
ephemeral RS256 key, serves a local JWKS endpoint, provisions viewer/editor/admin
principals through `app.bootstrap_identity`, and removes the issuer, keys,
containers, and volumes afterward. Production authentication defaults are not
changed. Responses API calls retain `store=false`.

## Result

The final run passed on 2026-08-27 with real OpenAI embeddings, the configured
`gpt-5.6-terra` answer model, and the configured local cross-encoder.

- Logical document/version 1: `5ea01c41-387b-43b6-9b76-16f8252a65f0`.
- Version-1 generation 1: `ae5b50e7-0b5a-4d46-9462-dd3ea3c23e06`.
- Replacement version 2: `e23d16b5-993d-489a-9a0d-47b28de639d3`.
- Version-2 generation 1: `80d6b927-ce12-4ace-8aca-34542a8be594`.
- Version-2 reindex generation 2: `97511158-eea4-43f4-959d-82731f633f8c`.
- Failed candidate version 3 remained failed and never changed either active
  pointer.

Version 1 remained searchable while version 2 was queued with the worker stopped.
After activation, keyword, semantic, hybrid, `/ask`, and a new conversation used
only version 2. During reindex, generation 1 remained searchable; afterward every
returned chunk belonged to generation 2 and no duplicate chunk IDs appeared.
Replacement, reindex, and deletion request replay returned the original jobs.

The historical version-1 conversation citation retained its real immutable version
identity after replacement. Hard deletion immediately excluded the document from
all retrieval/answer paths. Physical cleanup removed all versions, generations,
source units, chunks, embeddings, full-text rows, and source objects. The historical
citation became a content-free `deleted` tombstone; the minimal logical document
tombstone retained no private source fields. Conversation answer prose remains, as
documented.

## Counts and jobs

Initial ingestion, replacement, reindex, simulated failed replacement, and deletion
each ran once (`attempt_count=1`). The first four final states were respectively
`succeeded`, `succeeded`, `succeeded`, `failed`; the deletion job succeeded. Counts
were one active chunk/embedding/full-text row after version 1, two retained
historical/current rows after replacement, three after reindex, and zero after hard
deletion.

Storage reconciliation after deletion reported:

`expected_objects=0 missing_objects=0 orphan_objects=0`

## Provider usage

The successful final run made 15 `text-embedding-3-small` requests covering 15
inputs and 218 input/total tokens. Request latencies in milliseconds were:

`485.719, 510.930, 294.701, 263.400, 326.348, 348.581, 264.770, 312.778, 343.280, 289.573, 944.691, 339.207, 533.931, 317.400, 870.655`

It made three `gpt-5.6-terra` Responses calls:

| Call | Input | Output | Total | Generation ms |
| --- | ---: | ---: | ---: | ---: |
| Version-1 ask | 375 | 74 | 449 | 2254.057 |
| Version-1 conversation | 374 | 66 | 440 | 1595.337 |
| Version-2 ask | 374 | 73 | 447 | 1487.525 |

Total Terra usage was 1,123 input, 213 output, and 1,336 tokens. No rewrite provider
call was required. Earlier harness-development runs stopped at explicit assertions;
the table above is the exact reproducible successful-run accounting.

## Isolation and security

Viewer read and editor replacement/reindex permissions passed; viewer lifecycle
writes and editor deletion returned `403`; admin deletion passed; cross-tenant
resource access returned `404`. API, worker, PostgreSQL, and Redis were healthy at
the end of verification.

Redacted API/worker log inspection found no bearer token, Authorization header,
OpenAI key, synthetic source marker, vector, internal storage path, or raw provider
response. Only safe model/count/token/latency telemetry was retained.
