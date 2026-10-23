# One image for everything Python: the API, every worker role group and the one-shot jobs
# (alembic upgrade head, alembic current, the worker smoke). The command decides which.
# Build from the repository root:  docker buildx build -f api/Dockerfile .
# No secrets are baked in: all configuration is read from the runtime environment.

FROM ghcr.io/astral-sh/uv:0.7.2-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first so this layer is cached until the lockfile changes.
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api/README* ./
COPY api/src ./src
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12.10-slim-bookworm AS runtime

ARG VERSION=0.0.0
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="cashapp-api" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY api/alembic.ini ./alembic.ini
COPY api/alembic ./alembic
COPY deploy/scripts/smoke.sh /app/deploy/smoke.sh
RUN chmod 0555 /app/deploy/smoke.sh

USER 10001

EXPOSE 8000 8081

CMD ["uvicorn", "cashapp.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
