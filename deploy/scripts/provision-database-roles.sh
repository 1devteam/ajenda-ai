#!/usr/bin/env bash
set -euo pipefail

# Bootstrap PostgreSQL roles using a separately authorized admin connection.
# This script intentionally never prints connection strings or password values.
: "${AJENDA_DATABASE_BOOTSTRAP_URL:?set a privileged, non-runtime bootstrap URL}"
: "${AJENDA_API_DATABASE_PASSWORD:?set the API role password}"
: "${AJENDA_WORKER_DATABASE_PASSWORD:?set the worker role password}"
: "${AJENDA_ASSURANCE_DATABASE_PASSWORD:?set the assurance role password}"
: "${AJENDA_MIGRATOR_DATABASE_PASSWORD:?set the migrator role password}"

# psql's \getenv directives consume role credentials without exposing them in
# argv. Parse the privileged connection URL in-process and exec psql with
# libpq environment variables, so the URL (which may contain a password) is
# never present in the process argument list.
exec python - <<'PY'
from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

parsed = urlparse(os.environ["AJENDA_DATABASE_BOOTSTRAP_URL"])
if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path:
    raise SystemExit("AJENDA_DATABASE_BOOTSTRAP_URL must be a PostgreSQL URL")

os.environ["PGHOST"] = parsed.hostname
if parsed.port:
    os.environ["PGPORT"] = str(parsed.port)
if parsed.username:
    os.environ["PGUSER"] = unquote(parsed.username)
if parsed.password:
    os.environ["PGPASSWORD"] = unquote(parsed.password)
os.environ["PGDATABASE"] = parsed.path.lstrip("/")
os.execvp("psql", ["psql", "-v", "ON_ERROR_STOP=1", "-f", "deploy/sql/database_role_bootstrap.sql"])
PY
