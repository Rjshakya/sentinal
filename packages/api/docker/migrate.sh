#!/bin/sh
# Runs Alembic against $DATABASE_URL, then execs the app command.
# Idempotent: re-running on an up-to-date database is a no-op.
set -eu

cd /app

echo "running alembic migrations..."
python -m alembic -c alembic.ini upgrade head

exec "$@"