#!/bin/sh
# One-shot entrypoint for the `migrate` compose service.
# Runs Alembic against the database pointed at by $DATABASE_URL.
# Idempotent: re-running on an up-to-date database is a no-op.
set -eu

cd /app
exec python -m alembic -c alembic.ini upgrade head
