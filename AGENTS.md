# Codex Project Instructions

- Inspect existing files before editing and preserve existing working code.
- Work only on the requested milestone. Give a short plan before significant changes.
- Use `docs/PROJECT_SPEC.md` as the product source of truth and `docs/ROADMAP.md` for milestone order.
- Never store API keys, passwords, or secrets in Git. Keep model names and external providers configurable through environment variables.
- Use typed Python, clear service boundaries, and database migrations for schema changes.
- Add tests for every important behavior. Run relevant tests, linting, and type checks after changes.
- Report exactly what changed and what was verified.
- Treat uploaded documents as untrusted input.
- Enforce organization and user authorization in backend queries. Never trust organization IDs supplied by the frontend.
- Validate citation identifiers server-side.
- Do not introduce LangGraph until the deterministic RAG pipeline works.
- Do not claim performance or accuracy numbers that have not been measured.
- Update documentation whenever architecture or setup changes.

## Milestone 2 development commands

- Validate Compose: `docker compose config`
- Build and start: `docker compose up --build -d`
- Check services: `docker compose ps`
- Stop safely: `docker compose down`
- Install locked backend dependencies: `cd backend; uv sync --frozen`
- Run all backend tests with the Compose database (PowerShell): `cd backend; $env:DATABASE_URL = "postgresql+asyncpg://rag_assistant_dev:rag_assistant_dev@localhost:5432/rag_assistant_dev"; $env:RUN_DATABASE_TESTS = "1"; uv run pytest`
- Run backend linting: `cd backend; uv run ruff check .`
- Validate services: `docker compose config`
- Inspect the worker: `docker compose exec worker uv run --no-sync celery -A app.worker:celery_app inspect ping`
- Run a worker locally: `cd backend; uv run celery -A app.worker:celery_app worker --loglevel=INFO`
- Run parser/chunker tests: `cd backend; uv run pytest tests/test_parsing.py tests/test_cleaning_chunking.py`

## Database migration commands

- Apply migrations in Compose: `docker compose run --rm api uv run alembic upgrade head`
- Show the current revision: `docker compose run --rm api uv run alembic current`
- Show migration history: `docker compose run --rm api uv run alembic history`
- Reverse the latest migration for development verification only: `docker compose run --rm api uv run alembic downgrade -1`
- Never use runtime `create_all`; all schema changes require an Alembic revision.
