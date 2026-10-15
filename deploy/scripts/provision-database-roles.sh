#!/usr/bin/env bash
set -euo pipefail

# Bootstrap PostgreSQL roles using a separately authorized admin connection.
# This script intentionally never prints connection strings or password values.
: "${AJENDA_DATABASE_BOOTSTRAP_URL:?set a privileged, non-runtime bootstrap URL}"
: "${AJENDA_API_DATABASE_PASSWORD:?set the API role password}"
: "${AJENDA_WORKER_DATABASE_PASSWORD:?set the worker role password}"
: "${AJENDA_ASSURANCE_DATABASE_PASSWORD:?set the assurance role password}"
: "${AJENDA_MIGRATOR_DATABASE_PASSWORD:?set the migrator role password}"

# psql's \\getenv directives consume credentials without exposing them in argv.
# Keep ON_ERROR_STOP enabled so missing credentials/privileged DDL fail closed.
exec psql "$AJENDA_DATABASE_BOOTSTRAP_URL" \\
  -v ON_ERROR_STOP=1 \\
  -f deploy/sql/database_role_bootstrap.sql
