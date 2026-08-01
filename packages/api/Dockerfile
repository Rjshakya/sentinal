# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Copy only what uv needs to resolve the workspace. Editing api source
# after this layer will not bust the dependency-install cache.
COPY pyproject.toml uv.lock ./
COPY packages/api/pyproject.toml packages/api/pyproject.toml

RUN uv sync --frozen --no-dev --package api --no-install-project

# Now copy the api project source and install it as a real wheel so
# the venv is self-contained (no .pth files pointing at the build
# path, which would not exist in the runtime image).
COPY packages/api/src packages/api/src
RUN uv sync --frozen --no-dev --package api --no-editable


# ---- runtime ----
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

# libpq5 is needed by psycopg/asyncpg; curl powers the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl libpq5 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 app




# Prebuilt venv (all wheels, including the api package itself).
COPY --from=builder /build/.venv /app/.venv
# COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv

# Runtime files that are not part of the api package: the uvicorn
# entrypoint, alembic config + versions, and the migration entrypoint.
COPY packages/api/main.py /app/main.py
COPY packages/api/alembic.ini /app/alembic.ini
COPY packages/api/alembic /app/alembic
COPY --chmod=755 packages/api/docker/migrate.sh /app/docker/migrate.sh

USER app


HEALTHCHECK --interval=40s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

CMD [ "python", "main.py"]
