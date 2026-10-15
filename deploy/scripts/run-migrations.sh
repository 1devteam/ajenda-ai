#!/usr/bin/env bash
set -euo pipefail

export AJENDA_MIGRATION_CONTEXT=1

python - <<'PY'
from backend.app.config import get_settings

settings = get_settings()
settings.validate_database_identity(expected_identity="migrator")
PY

alembic upgrade head

python - <<'PY'
from backend.app.config import get_settings
from backend.db.vector_session import VectorDatabaseRuntime

settings = get_settings()
if settings.vector_db_enabled and settings.resolved_vector_database_url:
    runtime = VectorDatabaseRuntime(settings)
    try:
        runtime.ensure_schema()
    finally:
        runtime.dispose()
PY
