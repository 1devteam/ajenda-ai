#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="deploy/compose/docker-compose.prod.yml"
ENV_FILE="deploy/compose/.env.prod"

echo "== Staging Runtime Proof =="

# Ensure env file exists
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE"
  exit 1
fi

# Extract worker tenant
WORKER_TENANT_ID=$(grep '^AJENDA_WORKER_TENANT_ID=' "$ENV_FILE" | cut -d '=' -f2)

if [ -z "$WORKER_TENANT_ID" ]; then
  echo "AJENDA_WORKER_TENANT_ID not set"
  exit 1
fi

echo "Worker tenant: $WORKER_TENANT_ID"

# Create + queue task inside API container
TASK_ID=$(docker exec -i compose-api-1 python - <<PY
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
        slug="runtime-proof",
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

echo "Waiting for completion..."

sleep 5

STATUS=$(docker exec -i compose-api-1 python - <<PY
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.execution_task import ExecutionTask

task_id = "$TASK_ID"

runtime = DatabaseRuntime(get_settings())
db = runtime.session_factory()
task = db.get(ExecutionTask, task_id)

print(task.status)
PY
)

echo "Task status: $STATUS"

if [ "$STATUS" != "completed" ]; then
  echo "FAIL: task did not complete"
  exit 1
fi

echo "Checking Redis queues..."

PENDING=$(docker exec -i compose-redis-1 redis-cli llen ajenda:queue:${WORKER_TENANT_ID}:pending)
PROCESSING=$(docker exec -i compose-redis-1 redis-cli llen ajenda:queue:${WORKER_TENANT_ID}:processing)

echo "pending=$PENDING processing=$PROCESSING"

if [ "$PENDING" != "0" ] || [ "$PROCESSING" != "0" ]; then
  echo "FAIL: queues not drained"
  exit 1
fi

echo "PASS: runtime proof complete"
