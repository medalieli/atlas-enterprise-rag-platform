ARG PYTHON_IMAGE=python:3.12.14-slim-trixie@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.13@sha256:4de5495181a281bc744845b9579acf7b221d6791f99bcc211b9ec13f417c2853
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build

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
RUN mkdir -p /models && if [ "$DOWNLOAD_RERANKER" = "true" ]; then \
      uv run --no-sync python scripts/download_reranker.py; \
    fi

FROM ${PYTHON_IMAGE} AS runtime
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="Production RAG Assistant backend" \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.created=$BUILD_DATE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/app/.venv/bin:$PATH \
    HOME=/home/app RERANKER_MODEL_PATH=/models/reranker \
    DEBIAN_FRONTEND=noninteractive
# Pin the security update that was published after the immutable base was built.
# Perl is not used by the application and is removed from the runtime entirely;
# this also keeps a compiler-capable scripting runtime out of the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libssl3t64=3.5.7-1~deb13u2 \
      openssl=3.5.7-1~deb13u2 \
      openssl-provider-legacy=3.5.7-1~deb13u2 \
    && apt-get purge -y --allow-remove-essential perl-base \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /usr/local/lib/python3.12/site-packages/pip* \
      /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 \
    && groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app \
    --home-dir /home/app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/documents /models \
    && chown -R app:app /data/documents /models
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /models /models

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint \
    && chmod 0555 /usr/local/bin/docker-entrypoint

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=*"]
