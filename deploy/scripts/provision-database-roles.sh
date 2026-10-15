#!/usr/bin/env bash
set -euo pipefail

# Bootstrap PostgreSQL roles using a separately authorized admin connection.
# This script intentionally never prints connection strings or password values.
: "${AJENDA_DATABASE_BOOTSTRAP_URL:?set a privileged, non-runtime bootstrap URL}"
: "${AJENDA_API_DATABASE_PASSWORD:?set the API role password}"
: "${AJENDA_WORKER_DATABASE_PASSWORD:?set the worker role password}"
: "${AJENDA_ASSURANCE_DATABASE_PASSWORD:?set the assurance role password}"
: "${AJENDA_MIGRATOR_DATABASE_PASSWORD:?set the migrator role password}"

exec psql "$AJENDA_DATABASE_BOOTSTRAP_URL" \
  -v ON_ERROR_STOP=1 \
  -v api_password="$AJENDA_API_DATABASE_PASSWORD" \
  -v worker_password="$AJENDA_WORKER_DATABASE_PASSWORD" \
  -v assurance_password="$AJENDA_ASSURANCE_DATABASE_PASSWORD" \
  -v migrator_password="$AJENDA_MIGRATOR_DATABASE_PASSWORD" \
  -f deploy/sql/database_role_bootstrap.sql
