#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
PROOF_TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-60}"
PROOF_POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"

echo "== Staging Runtime Proof =="

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

WORKER_TENANT_ID=$(grep '^AJENDA_WORKER_TENANT_ID=' "$ENV_FILE" | cut -d '=' -f2)

if [ -z "$WORKER_TENANT_ID" ]; then
  echo "AJENDA_WORKER_TENANT_ID not set"
  exit 1
fi

echo "Worker tenant: $WORKER_TENANT_ID"

TASK_ID=$(compose exec -T api python - <<PY
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.tenant import Tenant
from backend.domain.mission import Mission
from backend.domain.execution_task import ExecutionTask
from backend.domain.enums import ExecutionTaskState
from backend.queue.adapters.redis_adapter import RedisQueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator
import uuid

tenant_id = "$WORKER_TENANT_ID"

settings = get_settings()
runtime = DatabaseRuntime(settings)
db = runtime.session_factory()
queue = RedisQueueAdapter(settings.queue_url)

tenant = db.get(Tenant, uuid.UUID(tenant_id))
if tenant is None:
    tenant = Tenant(
        id=uuid.UUID(tenant_id),
        name="runtime-proof",
        slug=f"runtime-proof-{tenant_id[:8]}",
        plan="free",
    )
    db.add(tenant)

mission = Mission(
    tenant_id=tenant_id,
    objective="runtime proof",
    status="running",
)
db.add(mission)
db.flush()

task = ExecutionTask(
    tenant_id=tenant_id,
    mission_id=mission.id,
    title="runtime proof task",
    description="proof",
    status=ExecutionTaskState.PLANNED.value,
    metadata_json={"task_type": "echo", "input": {"message": "proof"}},
    compliance_category="operational",
    jurisdiction="US-ALL",
    requires_human_review=False,
)
db.add(task)
db.commit()

ExecutionCoordinator(db, queue).queue_task(
    tenant_id=tenant_id,
    task_id=str(task.id),
)
db.commit()

print(task.id)
PY
)

echo "Task ID: $TASK_ID"
echo "Waiting for completion up to ${PROOF_TIMEOUT_SECONDS}s..."

STATUS=""
SECONDS_WAITED=0
while [ "$SECONDS_WAITED" -le "$PROOF_TIMEOUT_SECONDS" ]; do
  STATUS=$(compose exec -T api python - <<PY
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.execution_task import ExecutionTask

task_id = "$TASK_ID"

runtime = DatabaseRuntime(get_settings())
db = runtime.session_factory()
task = db.get(ExecutionTask, task_id)

print(task.status if task is not None else "missing")
PY
)

  echo "Task status after ${SECONDS_WAITED}s: $STATUS"

  if [ "$STATUS" = "completed" ]; then
    break
  fi

  sleep "$PROOF_POLL_SECONDS"
  SECONDS_WAITED=$((SECONDS_WAITED + PROOF_POLL_SECONDS))
done

if [ "$STATUS" != "completed" ]; then
  echo "FAIL: task did not complete before timeout"
  exit 1
fi

echo "Verifying worker lease metadata..."

WORKER_LEASE_ID=$(compose exec -T api python - <<PY
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.execution_task import ExecutionTask

task_id = "$TASK_ID"

runtime = DatabaseRuntime(get_settings())
db = runtime.session_factory()
task = db.get(ExecutionTask, task_id)
metadata = task.metadata_json if task is not None else {}
print(metadata.get("worker_lease_id", ""))
PY
)

if [ -z "$WORKER_LEASE_ID" ]; then
  echo "FAIL: completed task does not record worker_lease_id"
  exit 1
fi

echo "worker_lease_id=$WORKER_LEASE_ID"

echo "Waiting for Redis queues to drain..."

PENDING=""
PROCESSING=""
SECONDS_WAITED=0
while [ "$SECONDS_WAITED" -le "$PROOF_TIMEOUT_SECONDS" ]; do
  PENDING=$(compose exec -T redis redis-cli llen "ajenda:queue:${WORKER_TENANT_ID}:pending")
  PROCESSING=$(compose exec -T redis redis-cli llen "ajenda:queue:${WORKER_TENANT_ID}:processing")

  echo "Queue state after ${SECONDS_WAITED}s: pending=$PENDING processing=$PROCESSING"

  if [ "$PENDING" = "0" ] && [ "$PROCESSING" = "0" ]; then
    break
  fi

  sleep "$PROOF_POLL_SECONDS"
  SECONDS_WAITED=$((SECONDS_WAITED + PROOF_POLL_SECONDS))
done

if [ "$PENDING" != "0" ] || [ "$PROCESSING" != "0" ]; then
  echo "FAIL: queues not drained before timeout"
  exit 1
fi

echo "PASS: runtime proof complete"
