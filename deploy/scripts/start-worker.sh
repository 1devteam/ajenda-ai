#!/usr/bin/env bash
set -euo pipefail

exec python - <<'PY'
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.queue import build_queue_adapter
from backend.workers.tenant_scheduler import build_claim_target
from backend.workers.worker_loop import WorkerLoop

settings = get_settings()
settings.validate_runtime_contract()

queue_adapter = build_queue_adapter(settings)
if not queue_adapter.ping():
    raise SystemExit(f"queue adapter {settings.queue_adapter} failed startup ping")

database_runtime = DatabaseRuntime(settings)
claim_target = build_claim_target(settings, session_factory=database_runtime.session_factory)

try:
    WorkerLoop(
        session_factory=database_runtime.session_factory,
        queue=queue_adapter,
        worker_id=settings.worker_identity,
        claim_target=claim_target,
    ).run_forever()
finally:
    database_runtime.dispose()
PY