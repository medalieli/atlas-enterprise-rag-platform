# Production RAG Knowledge Assistant

Milestone 2 provides a minimal FastAPI service and PostgreSQL 17 development database with pgvector 0.8.6. It does not yet include application tables, document ingestion, retrieval, authentication, OpenAI calls, or a frontend.

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

## Troubleshooting

If Docker commands are unavailable or report that the daemon is not running, install/start Docker Desktop and verify with `docker --version` and `docker compose version`.

If port 8000 or 5432 is occupied, set a different host port in `.env`, for example `API_PORT=8001` or `POSTGRES_PORT=5433`. Container-to-container ports and the Compose `DATABASE_URL` do not change.

Inspect service state and logs with:

```powershell
docker compose ps
docker compose logs api postgres
```

The [project specification](docs/PROJECT_SPEC.md) defines the product, and the [roadmap](docs/ROADMAP.md) tracks later milestones.
