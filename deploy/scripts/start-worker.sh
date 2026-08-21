#!/usr/bin/env bash
set -euo pipefail

exec python - <<'PY'
from backend.app.config import get_settings
from backend.app.logging import configure_logging
from backend.db.session import DatabaseRuntime
from backend.db.vector_session import VectorDatabaseRuntime
from backend.queue import build_queue_adapter
from backend.workers.tenant_scheduler import build_claim_target
from backend.workers.worker_loop import WorkerLoop

settings = get_settings()
configure_logging(settings)
settings.validate_runtime_contract()

queue_adapter = build_queue_adapter(settings)
if not queue_adapter.ping():
    raise SystemExit(f"queue adapter {settings.queue_adapter} failed startup ping")

database_runtime = DatabaseRuntime(settings)
vector_database_runtime = None
if settings.vector_db_enabled and settings.resolved_vector_database_url:
    vector_database_runtime = VectorDatabaseRuntime(settings)
    vector_database_runtime.ensure_schema()
    if not vector_database_runtime.ping():
        raise SystemExit("vector database failed startup ping")

claim_target = build_claim_target(
    settings,
    session_factory=database_runtime.session_factory,
    queue=queue_adapter,
)

try:
    WorkerLoop(
        session_factory=database_runtime.session_factory,
        vector_session_factory=(
            vector_database_runtime.session_factory if vector_database_runtime is not None else None
        ),
        queue=queue_adapter,
        worker_id=settings.worker_identity,
        claim_target=claim_target,
    ).run_forever()
finally:
    if vector_database_runtime is not None:
        vector_database_runtime.dispose()
    database_runtime.dispose()
PY
