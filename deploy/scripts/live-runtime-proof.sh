#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
API_BASE_URL="${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}"
PROMETHEUS_BASE_URL="${AJENDA_PROOF_PROMETHEUS_BASE_URL:-http://localhost:9090}"
PROMETHEUS_JOB_NAME="${AJENDA_PROOF_PROMETHEUS_JOB_NAME:-ajenda-api}"
TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-90}"
POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"
CURL_CONNECT_TIMEOUT_SECONDS="${AJENDA_PROOF_CURL_CONNECT_TIMEOUT_SECONDS:-5}"
CURL_MAX_TIME_SECONDS="${AJENDA_PROOF_CURL_MAX_TIME_SECONDS:-10}"

log() {
  printf '[live-runtime-proof] %s\n' "$*"
}

fail() {
  printf '[live-runtime-proof] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

compose() {
  docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

wait_for_http_ok() {
  local url="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))

  until curl \
    --fail \
    --silent \
    --show-error \
    --connect-timeout "$CURL_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$CURL_MAX_TIME_SECONDS" \
    "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      fail "timed out waiting for HTTP 200 from $url"
    fi
    sleep "$POLL_SECONDS"
  done
}

curl_body() {
  local url="$1"
  curl \
    --fail \
    --silent \
    --show-error \
    --connect-timeout "$CURL_CONNECT_TIMEOUT_SECONDS" \
    --max-time "$CURL_MAX_TIME_SECONDS" \
    "$url"
}

assert_body_contains() {
  local body="$1"
  local expected="$2"
  if ! grep -q "$expected" <<<"$body"; then
    fail "expected response body to contain: $expected"
  fi
}

wait_for_prometheus_target_up() {
  local job_name="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local targets_body

  while (( SECONDS < deadline )); do
    targets_body="$(curl_body "$PROMETHEUS_BASE_URL/api/v1/targets?state=active")"
    if python - <<'PY' "$targets_body" "$job_name"
from __future__ import annotations

import json
import sys

payload = json.loads(sys.argv[1])
job_name = sys.argv[2]

if payload.get("status") != "success":
    raise SystemExit(1)

for target in payload.get("data", {}).get("activeTargets", []):
    labels = target.get("labels", {})
    if labels.get("job") == job_name and target.get("health") == "up":
        raise SystemExit(0)

raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep "$POLL_SECONDS"
  done

  fail "timed out waiting for Prometheus target ${job_name} to be up"
}

require_command docker
require_command curl
require_command grep
require_command python

if [[ ! -f "$COMPOSE_FILE" ]]; then
  fail "compose file not found: $COMPOSE_FILE"
fi

if [[ ! -f "$COMPOSE_ENV_FILE" ]]; then
  fail "compose env file not found: $COMPOSE_ENV_FILE"
fi

log "validating compose configuration"
compose config --quiet

log "resetting prior compose volumes (avoids stale DB credentials after env rotation)"
compose down -v --remove-orphans >/dev/null 2>&1 || true

log "starting compose services"
compose up -d --build db redis migrate api worker prometheus otel-collector

log "checking compose service state"
compose ps

log "checking api health/readiness"
wait_for_http_ok "$API_BASE_URL/health"
wait_for_http_ok "$API_BASE_URL/readiness"
wait_for_http_ok "$API_BASE_URL/v1/system/health"
wait_for_http_ok "$API_BASE_URL/v1/system/readiness"

log "checking postgres readiness"
compose exec -T db pg_isready -U ajenda -d ajenda >/dev/null

log "checking redis ping"
compose exec -T redis redis-cli PING | grep -q '^PONG$'

log "queueing real echo task for configured worker tenant and waiting for worker completion"
proof_json="$(
  compose exec -T \
    -e AJENDA_PROOF_TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
    -e AJENDA_PROOF_POLL_SECONDS="$POLL_SECONDS" \
    api python - <<'PY'
from __future__ import annotations

import json
import os
import time
import uuid

from sqlalchemy import func, select

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue import build_queue_adapter
from backend.services.execution_coordinator import ExecutionCoordinator

settings = get_settings()
settings.validate_runtime_contract()
queue_adapter = build_queue_adapter(settings)
database_runtime = DatabaseRuntime(settings)
worker_tenant_id = settings.worker_tenant_id
slug_suffix = uuid.uuid4().hex[:10]
timeout_seconds = float(os.environ["AJENDA_PROOF_TIMEOUT_SECONDS"])
poll_seconds = float(os.environ["AJENDA_PROOF_POLL_SECONDS"])

def scalar_count(session, stmt) -> int:
    return int(session.scalar(stmt) or 0)

try:
    session = database_runtime.session_factory()
    try:
        tenant_uuid = uuid.UUID(worker_tenant_id)
        tenant = session.get(Tenant, tenant_uuid)
        if tenant is None:
            tenant = Tenant(
                id=tenant_uuid,
                name="Live Runtime Proof Tenant",
                slug=f"live-runtime-proof-{slug_suffix}",
                plan="free",
            )
            session.add(tenant)

        mission = Mission(
            tenant_id=worker_tenant_id,
            objective="Live runtime proof mission",
            status="running",
        )
        session.add(mission)
        session.flush()

        task = ExecutionTask(
            tenant_id=worker_tenant_id,
            mission_id=mission.id,
            title="Live runtime proof echo task",
            description="Proof task created by deploy/scripts/live-runtime-proof.sh",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={"task_type": "echo", "input": {"message": "live-runtime-proof"}},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        session.add(task)
        session.flush()
        task_id = task.id

        queued = ExecutionCoordinator(session, queue_adapter).queue_task(
            tenant_id=worker_tenant_id,
            task_id=task_id,
        )
        if not queued.ok:
            raise RuntimeError(queued.reason or "queue_task rejected proof task")
        session.commit()
    finally:
        session.close()

    deadline = time.monotonic() + timeout_seconds
    final = None
    while time.monotonic() < deadline:
        session = database_runtime.session_factory()
        try:
            current = session.get(ExecutionTask, task_id)
            if current is not None and current.status in {
                ExecutionTaskState.COMPLETED.value,
                ExecutionTaskState.FAILED.value,
                ExecutionTaskState.DEAD_LETTERED.value,
            }:
                final = current.status
                break
        finally:
            session.close()
        time.sleep(poll_seconds)

    if final != ExecutionTaskState.COMPLETED.value:
        raise RuntimeError(f"proof task did not complete; final_status={final!r}; task_id={task_id}")

    session = database_runtime.session_factory()
    try:
        task = session.get(ExecutionTask, task_id)
        if task is None:
            raise RuntimeError("proof task disappeared")
        lease_id_raw = task.metadata_json.get("worker_lease_id")
        if not isinstance(lease_id_raw, str):
            raise RuntimeError("proof task missing worker_lease_id")
        lease_id = uuid.UUID(lease_id_raw)
        lease = session.get(WorkerLease, lease_id)
        if lease is None:
            raise RuntimeError("proof lease disappeared")
        if lease.status != WorkerLeaseState.RELEASED.value:
            raise RuntimeError(f"proof lease was not released: {lease.status}")
        actual_worker_id = lease.holder_identity

        lineage_count = scalar_count(
            session,
            select(func.count())
            .select_from(LineageRecord)
            .where(
                LineageRecord.tenant_id == worker_tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            ),
        )
        if lineage_count != 1:
            raise RuntimeError(f"expected one task_output lineage record, found {lineage_count}")

        audit_count = scalar_count(
            session,
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == worker_tenant_id,
                AuditEvent.action == "task_completed",
                AuditEvent.actor == actual_worker_id,
                AuditEvent.payload_json["task_id"].astext == str(task_id),
                AuditEvent.payload_json["lease_id"].astext == str(lease_id),
            ),
        )
        if audit_count != 1:
            raise RuntimeError(f"expected one task_completed audit event, found {audit_count}")

        print(
            json.dumps(
                {
                    "tenant_id": worker_tenant_id,
                    "worker_id": actual_worker_id,
                    "task_id": str(task_id),
                    "lease_id": str(lease_id),
                    "task_status": task.status,
                    "lease_status": lease.status,
                    "lineage_count": lineage_count,
                    "audit_count": audit_count,
                },
                sort_keys=True,
            )
        )
    finally:
        session.close()
finally:
    database_runtime.dispose()
PY
)"

log "proof result: $proof_json"

proof_task_id="$(python - <<'PY' "$proof_json"
import json
import sys
print(json.loads(sys.argv[1])["task_id"])
PY
)"
proof_tenant_id="$(python - <<'PY' "$proof_json"
import json
import sys
print(json.loads(sys.argv[1])["tenant_id"])
PY
)"

log "checking live observability metrics"
metrics_body="$(curl_body "$API_BASE_URL/v1/observability/metrics")"
assert_body_contains "$metrics_body" "ajenda_tasks_completed"
assert_body_contains "$metrics_body" "ajenda_active_leases"
assert_body_contains "$metrics_body" "ajenda_worker_utilization"

log "checking Prometheus readiness and scrape target health"
wait_for_http_ok "$PROMETHEUS_BASE_URL/-/ready"
wait_for_prometheus_target_up "$PROMETHEUS_JOB_NAME"

log "checking Redis lease cleanup for proof task"
lease_value="$(compose exec -T redis redis-cli GET "ajenda:queue:${proof_tenant_id}:lease:${proof_task_id}")"

if [[ -n "$lease_value" ]]; then
  fail "expected Redis lease key to be absent; got $lease_value"
fi

log "queueing low-risk GTM lead enrich proof task"
gtm_proof_json="$(
  compose exec -T \
    -e AJENDA_PROOF_TIMEOUT_SECONDS="$TIMEOUT_SECONDS" \
    -e AJENDA_PROOF_POLL_SECONDS="$POLL_SECONDS" \
    -e AJENDA_PROOF_WORKER_TENANT_ID="$proof_tenant_id" \
    api python - <<'PY'
from __future__ import annotations

import json
import os
import time
import uuid

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.queue import build_queue_adapter
from backend.services.execution_coordinator import ExecutionCoordinator

settings = get_settings()
worker_tenant_id = os.environ["AJENDA_PROOF_WORKER_TENANT_ID"]
queue_adapter = build_queue_adapter(settings)
database_runtime = DatabaseRuntime(settings)
timeout_seconds = float(os.environ["AJENDA_PROOF_TIMEOUT_SECONDS"])
poll_seconds = float(os.environ["AJENDA_PROOF_POLL_SECONDS"])

try:
    session = database_runtime.session_factory()
    try:
        mission = Mission(
            tenant_id=worker_tenant_id,
            objective="Live runtime GTM proof mission",
            status="running",
            metadata_json={"source": "live-runtime-proof", "action": "gtm.lead_enrich"},
        )
        session.add(mission)
        session.flush()

        task = ExecutionTask(
            tenant_id=worker_tenant_id,
            mission_id=mission.id,
            title="GTM lead enrich proof",
            description="Proof task for gtm.lead_enrich via tool.invoke",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "action": "gtm.lead_enrich",
                    "input": {"company": "Proof Co", "domain": "proof.example.com"},
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        session.add(task)
        session.flush()
        task_id = task.id

        queued = ExecutionCoordinator(session, queue_adapter).queue_task(
            tenant_id=worker_tenant_id,
            task_id=task_id,
        )
        if not queued.ok:
            raise RuntimeError(queued.reason or "gtm proof queue_task rejected")
        session.commit()
    finally:
        session.close()

    deadline = time.monotonic() + timeout_seconds
    final = None
    while time.monotonic() < deadline:
        session = database_runtime.session_factory()
        try:
            current = session.get(ExecutionTask, task_id)
            if current is not None and current.status in {
                ExecutionTaskState.COMPLETED.value,
                ExecutionTaskState.FAILED.value,
                ExecutionTaskState.DEAD_LETTERED.value,
            }:
                final = current.status
                break
        finally:
            session.close()
        time.sleep(poll_seconds)

    if final != ExecutionTaskState.COMPLETED.value:
        raise RuntimeError(f"gtm proof task did not complete; final_status={final!r}; task_id={task_id}")

    print(json.dumps({"task_id": str(task_id), "action": "gtm.lead_enrich", "task_status": final}, sort_keys=True))
finally:
    database_runtime.dispose()
PY
)"

log "gtm proof result: $gtm_proof_json"

log "running brain capstone slice (draft → approve → CRM; send optional)"
capstone_proof_json="$(
  compose exec -T \
    -e AJENDA_PROOF_WORKER_TENANT_ID="$proof_tenant_id" \
    -e AJENDA_BRAIN_CAPSTONE_SEND="${AJENDA_BRAIN_CAPSTONE_SEND:-}" \
    api python deploy/scripts/brain-capstone-runtime-proof.py
)"
log "brain capstone proof result: $capstone_proof_json"
python - <<'PY' "$capstone_proof_json"
from __future__ import annotations

import json
import sys

payload = json.loads(sys.argv[1])
if not payload.get("ok"):
    raise SystemExit(f"brain capstone proof failed: {payload}")
artifact_id = payload.get("artifact_id")
if not artifact_id:
    raise SystemExit("brain capstone proof missing artifact_id")
PY

if [[ "${AJENDA_PROOF_PLUGIN_LANE_ENABLED:-}" == "1" ]]; then
  log "running optional env-gated plugin runtime lane"
  export AJENDA_PROOF_API_BASE_URL="$API_BASE_URL"
  export AJENDA_PROOF_COMPOSE_FILE="$COMPOSE_FILE"
  export AJENDA_PROOF_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE"
  bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/plugin-runtime-proof.sh"
else
  log "plugin lane skipped (set AJENDA_PROOF_PLUGIN_LANE_ENABLED=1 and provider tokens to enable)"
fi

log "live runtime proof passed"
