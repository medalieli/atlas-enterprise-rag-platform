# Production RAG Knowledge Assistant

The Milestone 13 Next.js workspace, OAuth/OIDC Backend-for-Frontend setup, role
behavior and frontend commands are documented in
[`docs/FRONTEND.md`](docs/FRONTEND.md). The browser application runs at
<http://localhost:3000> in Docker Compose.

Document replacement, immutable source versions, generation-based reindexing, and
asynchronous hard deletion are described in
[`docs/DOCUMENT_LIFECYCLE.md`](docs/DOCUMENT_LIFECYCLE.md).

Lifecycle requests use authenticated collection scope and idempotency keys:

```text
POST   /collections/{collection_id}/documents/{document_id}/versions
POST   /collections/{collection_id}/documents/{document_id}/reindex
DELETE /collections/{collection_id}/documents/{document_id}
GET    /collections/{collection_id}/documents/{document_id}
GET    /collections/{collection_id}/documents/{document_id}/versions
GET    /collections/{collection_id}/documents/{document_id}/versions/{version_id}
```

Milestones 10–13 add external OAuth/OIDC access-token validation, internal principals,
tenant-scoped conversations and document lifecycle management, plus the authenticated
Next.js frontend. Milestone 14 evaluation/observability and Milestone 15 deployment
hardening remain explicitly deferred.

## Prerequisites

- Docker Desktop (or Docker Engine) with Docker Compose v2
- Optional for running tools outside containers: Python 3.12 and [uv](https://docs.astral.sh/uv/)

## Configure the environment

Compose has safe local defaults, so no environment file is required. To customize ports or credentials, copy `.env.example` to `.env` and edit the copy. Never commit `.env` or production credentials.

If database credentials are changed, update `DATABASE_URL` to match. Inside Compose, its hostname must remain `postgres`.

## Start and stop

From the repository root:

```powershell
docker compose up --build -d
docker compose ps
```

Stop services safely while preserving the database volume:

```powershell
docker compose down
```

Warning: `docker compose down -v` permanently deletes the local PostgreSQL volume and all data in it.

## Local endpoints

- Application information: <http://localhost:8000/>
- Liveness: <http://localhost:8000/health/live>
- Database and pgvector readiness: <http://localhost:8000/health/ready>
- Swagger UI: <http://localhost:8000/docs>
- Upload: `POST /collections/{collection_id}/documents`
- Job status: `GET /processing-jobs/{job_id}`
- Semantic retrieval: `POST /collections/{collection_id}/semantic-search`
- Keyword retrieval: `POST /collections/{collection_id}/keyword-search`
- Hybrid retrieval: `POST /collections/{collection_id}/hybrid-search`
- Reranked retrieval: `POST /collections/{collection_id}/reranked-search`
- Grounded answers: `POST /collections/{collection_id}/ask`
- Conversations: `POST /collections/{collection_id}/conversations`
- Conversation turns: `POST /collections/{collection_id}/conversations/{conversation_id}/messages`
- Current identity: `GET /auth/me`
- Authorized document list: `GET /collections/{collection_id}/documents`
- Authorized immutable source: `GET /collections/{collection_id}/documents/{document_id}/versions/{version_id}/source`
- List collections: `GET /collections?tenant_id=<TENANT_UUID>`
- Create collection: `POST /collections`

If `API_PORT` is changed, replace `8000` in these URLs with that port.

## Tests and linting

Run the complete suite, including the database integration test, after Compose is healthy:

```powershell
Set-Location backend
uv sync --frozen
$env:DATABASE_URL = "postgresql+asyncpg://rag_assistant_dev:rag_assistant_dev@localhost:5432/rag_assistant_dev"
$env:RUN_DATABASE_TESTS = "1"
uv run pytest
uv run ruff check .
```

To run unit tests without PostgreSQL, omit `RUN_DATABASE_TESTS`; the database integration test will be reported as skipped.

## Database migrations

Apply all migrations from the repository root after PostgreSQL is healthy:

```powershell
docker compose run --rm api uv run alembic upgrade head
docker compose run --rm api uv run alembic current
```

Alembic reads `DATABASE_URL` through the same typed settings as the application. Inside Compose, the database hostname is `postgres`. Running `upgrade head` repeatedly is safe; already-applied revisions are not executed again.

For host-side development, run the equivalent commands from `backend` after setting `DATABASE_URL` to the mapped host port. Do not use SQLAlchemy `create_all` for application schema changes.

The [Milestone 3 data-model guide](docs/DATA_MODEL.md) explains the tables, tenant boundaries, delete behavior, and decisions deferred to later milestones.

The [Milestone 4 ingestion guide](docs/INGESTION.md) explains upload validation,
storage, trusted development identity, job states, retries, idempotency, and operational
commands. Example requests are available through Swagger after configuring a development
identity and seed records; never send tenant identity in upload input.

The [Milestone 5 parsing guide](docs/PARSING.md) documents parser limits, cleaning and
chunking rules, fingerprints, exact source traceability, and unsupported document features.

The [Milestone 6 embedding guide](docs/EMBEDDINGS.md) documents provider configuration,
batching, fingerprints, atomic ingestion, backfill, vector indexing, semantic search,
cost/privacy considerations, and limitations.

The [Milestone 7 retrieval guide](docs/RETRIEVAL.md) documents PostgreSQL full-text
representation, keyword search, secured candidate retrieval, Reciprocal Rank Fusion,
score interpretation, operational migration tradeoffs, and deferred functionality.

The [Milestone 8 filtering and reranking guide](docs/RERANKING.md) documents upload
metadata, shared filter semantics, indexed PostgreSQL predicates, bounded local
cross-encoder inference, score interpretation, and failure behavior.

The [Milestone 9 answer and citation guide](docs/ANSWERS.md) documents bounded
context construction, the grounding prompt, the Responses API configuration,
strict output validation, trusted citation resolution, privacy, and safe failures.

Example grounded request:

```json
{
  "query": "How long do enterprise customers have to request a refund?",
  "retrieval_count": 8,
  "filters": {"departments": ["legal"], "document_types": ["policy"]}
}
```

The response status is `answered`, `insufficient_context`, or
`conflicting_sources`. Factual claims contain numeric markers matching citations
whose document and source-location fields were resolved by the server.

The [Milestone 10 authentication guide](docs/AUTHENTICATION.md) documents external
issuer/JWKS setup, strict JWT validation, identity provisioning, roles, collection
management, tenant isolation, key rotation, TLS and revocation limitations. Business
requests use `Authorization: Bearer <ACCESS_TOKEN>`; the API validates tokens but
does not issue them.

The [Milestone 11 conversation guide](docs/CONVERSATIONS.md) documents PostgreSQL-owned
history, bounded Luna follow-up rewriting, clarification, idempotent serialized turns,
and current-turn citation revalidation. The existing stateless `/ask` endpoint remains
unchanged.

## Troubleshooting

If Docker commands are unavailable or report that the daemon is not running, install/start Docker Desktop and verify with `docker --version` and `docker compose version`.

If port 8000 or 5432 is occupied, set a different host port in `.env`, for example `API_PORT=8001` or `POSTGRES_PORT=5433`. Container-to-container ports and the Compose `DATABASE_URL` do not change.

Inspect service state and logs with:

```powershell
docker compose ps
docker compose logs api postgres
```

The [project specification](docs/PROJECT_SPEC.md) defines the product, and the [roadmap](docs/ROADMAP.md) tracks later milestones.
