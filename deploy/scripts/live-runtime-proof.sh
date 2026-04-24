#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
API_BASE_URL="${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}"
TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-90}"
POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"

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

api_port() {
  python - <<'PY' "$API_BASE_URL"
from __future__ import annotations

import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
if parsed.port is not None:
    print(parsed.port)
elif parsed.scheme == "https":
    print(443)
else:
    print(80)
PY
}

assert_api_port_available() {
  local port="$1"
  python - <<'PY' "$port" || fail "API bind port ${port} is already in use; stop the process/container using it or run the proof after freeing port ${port}"
from __future__ import annotations

import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
PY
}

wait_for_http_ok() {
  local url="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))

  until curl -fsS "$url" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      fail "timed out waiting for HTTP 200 from $url"
    fi
    sleep "$POLL_SECONDS"
  done
}

require_command docker
require_command curl
require_command python

if [[ ! -f "$COMPOSE_FILE" ]]; then
  fail "compose file not found: $COMPOSE_FILE"
fi

log "validating compose configuration"
docker compose -f "$COMPOSE_FILE" config --quiet

API_PORT="$(api_port)"
assert_api_port_available "$API_PORT"

log "starting compose services"
docker compose -f "$COMPOSE_FILE" up -d --build db redis migrate api worker

log "checking compose service state"
docker compose -f "$COMPOSE_FILE" ps

log "checking api health/readiness"
wait_for_http_ok "$API_BASE_URL/health"
wait_for_http_ok "$API_BASE_URL/readiness"

log "checking postgres readiness"
docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U ajenda -d ajenda >/dev/null

log "checking redis ping"
docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli PING | grep -q '^PONG$'

log "queueing real echo task for configured worker tenant and waiting for worker completion"
proof_json="$(
  docker compose -f "$COMPOSE_FILE" exec -T \
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

log "checking Redis lease cleanup for proof task"
lease_value="$(docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli GET "ajenda:queue:${proof_tenant_id}:lease:${proof_task_id}")"

if [[ -n "$lease_value" ]]; then
  fail "expected Redis lease key to be absent; got $lease_value"
fi

log "live runtime proof passed"
