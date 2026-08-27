FROM ghcr.io/astral-sh/uv:0.8.13 AS uv

FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY scripts/download_reranker.py ./scripts/download_reranker.py
ARG DOWNLOAD_RERANKER=true
RUN if [ "$DOWNLOAD_RERANKER" = "true" ]; then \
      uv run --no-sync python scripts/download_reranker.py; \
    fi

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
