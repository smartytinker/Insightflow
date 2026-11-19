#!/bin/sh
# Container entrypoint: wait for PostgreSQL, run migrations, start the API.
set -e

attempt=1
max_attempts=30
while [ "$attempt" -le "$max_attempts" ]; do
  if alembic upgrade head; then
    echo "Database migrations applied."
    break
  fi
  echo "Migration attempt $attempt/$max_attempts failed; retrying in 2s..."
  attempt=$((attempt + 1))
  sleep 2
done

if [ "$attempt" -gt "$max_attempts" ]; then
  echo "Could not apply database migrations." >&2
  exit 1
fi

exec "$@"
