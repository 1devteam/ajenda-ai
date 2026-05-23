#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
TASK_COUNT="${AJENDA_SCALE_PROOF_TASK_COUNT:-25}"
PROOF_TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-120}"
PROOF_POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"

echo "== Staging Scale Proof =="

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

metric_value() {
  local metric_name="$1"
  curl -fsS http://localhost:8000/v1/observability/metrics | awk -v metric="$metric_name" '$1 == metric {print $2}'
}

WORKER_TENANT_ID=$(grep '^AJENDA_WORKER_TENANT_ID=' "$ENV_FILE" | cut -d '=' -f2)

if [ -z "$WORKER_TENANT_ID" ]; then
  echo "AJENDA_WORKER_TENANT_ID not set"
  exit 1
fi

echo "Worker tenant: $WORKER_TENANT_ID"
echo "Task count: $TASK_COUNT"

DEAD_LETTERS_BEFORE=$(metric_value "ajenda_dead_letter_count")
ACTIVE_LEASES_BEFORE=$(metric_value "ajenda_active_leases")

echo "baseline metrics: dead_letters=${DEAD_LETTERS_BEFORE:-missing} active_leases=${ACTIVE_LEASES_BEFORE:-missing}"

if [ -z "${DEAD_LETTERS_BEFORE:-}" ]; then
  echo "FAIL: missing ajenda_dead_letter_count metric before proof"
  exit 1
fi

if [ -z "${ACTIVE_LEASES_BEFORE:-}" ]; then
  echo "FAIL: missing ajenda_active_leases metric before proof"
  exit 1
fi

TASK_IDS=$(compose exec -T api python - <<PY
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
task_count = int("$TASK_COUNT")

settings = get_settings()
runtime = DatabaseRuntime(settings)
db = runtime.session_factory()
queue = RedisQueueAdapter(settings.queue_url)

tenant = db.get(Tenant, uuid.UUID(tenant_id))
if tenant is None:
    tenant = Tenant(
        id=uuid.UUID(tenant_id),
        name="scale-proof",
        slug=f"scale-proof-{tenant_id[:8]}",
        plan="free",
    )
    db.add(tenant)

mission = Mission(
    tenant_id=tenant_id,
    objective="scale proof",
    status="running",
)
db.add(mission)
db.flush()

task_ids = []
for index in range(task_count):
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission.id,
        title=f"scale proof task {index}",
        description="scale proof",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json={"task_type": "echo", "input": {"message": f"proof-{index}"}},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    db.add(task)
    db.flush()

    ExecutionCoordinator(db, queue).queue_task(
        tenant_id=tenant_id,
        task_id=str(task.id),
    )
    task_ids.append(str(task.id))

db.commit()

print("\\n".join(task_ids))
PY
)

echo "Queued tasks:"
echo "$TASK_IDS"

echo "Waiting for all tasks to complete up to ${PROOF_TIMEOUT_SECONDS}s..."

COMPLETED_COUNT=0
FAILED_COUNT=0
UNIQUE_LEASES=0
STATUS_LIST=""
SECONDS_WAITED=0

while [ "$SECONDS_WAITED" -le "$PROOF_TIMEOUT_SECONDS" ]; do
  RESULT=$(compose exec -T api python - <<PY
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.execution_task import ExecutionTask

task_ids = """$TASK_IDS""".splitlines()
task_ids = [line.strip() for line in task_ids if line.strip()]

runtime = DatabaseRuntime(get_settings())
db = runtime.session_factory()

statuses = []
lease_ids = []

for task_id in task_ids:
    task = db.get(ExecutionTask, task_id)
    if task is None:
        statuses.append("missing")
        continue

    statuses.append(task.status)
    metadata = task.metadata_json or {}
    lease_id = metadata.get("worker_lease_id")
    if lease_id:
        lease_ids.append(lease_id)

completed = sum(1 for status in statuses if status == "completed")
failed = sum(1 for status in statuses if status in {"failed", "dead_lettered", "cancelled", "missing"})
unique_leases = len(set(lease_ids))

print(f"{completed}|{failed}|{unique_leases}|{','.join(statuses)}")
PY
)

  COMPLETED_COUNT=$(echo "$RESULT" | cut -d '|' -f1)
  FAILED_COUNT=$(echo "$RESULT" | cut -d '|' -f2)
  UNIQUE_LEASES=$(echo "$RESULT" | cut -d '|' -f3)
  STATUS_LIST=$(echo "$RESULT" | cut -d '|' -f4)

  echo "after ${SECONDS_WAITED}s: completed=$COMPLETED_COUNT failed=$FAILED_COUNT unique_leases=$UNIQUE_LEASES"

  if [ "$COMPLETED_COUNT" = "$TASK_COUNT" ]; then
    break
  fi

  if [ "$FAILED_COUNT" != "0" ]; then
    echo "FAIL: one or more tasks failed: $STATUS_LIST"
    exit 1
  fi

  sleep "$PROOF_POLL_SECONDS"
  SECONDS_WAITED=$((SECONDS_WAITED + PROOF_POLL_SECONDS))
done

if [ "$COMPLETED_COUNT" != "$TASK_COUNT" ]; then
  echo "FAIL: not all tasks completed before timeout"
  echo "statuses=$STATUS_LIST"
  exit 1
fi

if [ "$UNIQUE_LEASES" != "$TASK_COUNT" ]; then
  echo "FAIL: expected one worker lease per completed task"
  echo "unique_leases=$UNIQUE_LEASES task_count=$TASK_COUNT"
  exit 1
fi

echo "Waiting for Redis queues to drain..."

PENDING=""
PROCESSING=""
SECONDS_WAITED=0

while [ "$SECONDS_WAITED" -le "$PROOF_TIMEOUT_SECONDS" ]; do
  PENDING=$(compose exec -T redis redis-cli llen "ajenda:queue:${WORKER_TENANT_ID}:pending")
  PROCESSING=$(compose exec -T redis redis-cli llen "ajenda:queue:${WORKER_TENANT_ID}:processing")

  echo "queue after ${SECONDS_WAITED}s: pending=$PENDING processing=$PROCESSING"

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

DEAD_LETTERS_AFTER=$(metric_value "ajenda_dead_letter_count")
ACTIVE_LEASES_AFTER=$(metric_value "ajenda_active_leases")

echo "final metrics: dead_letters=$DEAD_LETTERS_AFTER active_leases=$ACTIVE_LEASES_AFTER"

if [ "${DEAD_LETTERS_AFTER:-missing}" != "$DEAD_LETTERS_BEFORE" ]; then
  echo "FAIL: dead-letter count changed during proof"
  echo "before=$DEAD_LETTERS_BEFORE after=$DEAD_LETTERS_AFTER"
  exit 1
fi

echo "active lease metric is system-wide; proof relies on proof-task lease IDs plus Redis drain instead of asserting global zero"

echo "PASS: staging scale proof complete"
