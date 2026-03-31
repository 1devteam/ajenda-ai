#!/usr/bin/env bash
set -euo pipefail

exec python - <<'PY'
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.queue import build_queue_adapter
from backend.workers.worker_loop import WorkerLoop

settings = get_settings()
settings.validate_runtime_contract()

queue_adapter = build_queue_adapter(settings)
if not queue_adapter.ping():
    raise SystemExit(f"queue adapter {settings.queue_adapter} failed startup ping")

database_runtime = DatabaseRuntime(settings)

try:
    WorkerLoop(
        session_factory=database_runtime.session_factory,
        queue=queue_adapter,
        worker_id=settings.worker_identity,
        tenant_id=settings.worker_tenant_id,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    ).run_forever()
finally:
    database_runtime.dispose()
PY
