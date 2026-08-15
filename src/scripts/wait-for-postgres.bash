#!/usr/bin/env bash

set -euo pipefail

database_host="${POSTGRES_HOST:-db}"
database_port="${POSTGRES_PORT:-5432}"

echo "Waiting for PostgreSQL at ${database_host}:${database_port}..."
until pg_isready --quiet --host "$database_host" --port "$database_port"; do
    sleep 2
done
echo "PostgreSQL is ready."
