#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$SCRIPT_DIR/../compose/docker-compose.prod.yml}"
API_URL="${API_URL:-http://localhost:8000/v1}"
TENANT_ID="${TENANT_ID:-00000000-0000-0000-0000-000000000111}"
MISSION_ID=""
EXPECTED_TASKS=1
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-1}"
MAX_POLLS="${MAX_POLLS:-120}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

json_get() { jq -r "$1"; }

redis_exec() {
  local cmd="$1"
  local redis_service
  redis_service="$(compose config --services | awk '/^redis$/{print; exit}')"
  [[ -n "$redis_service" ]] || { echo "redis service not found" >&2; return 1; }
  compose exec -T "$redis_service" redis-cli $cmd
}

poll_until() {
  local description="$1" check_cmd="$2"
  local i=0
  until eval "$check_cmd"; do
    i=$((i + 1))
    if [[ "$i" -ge "$MAX_POLLS" ]]; then
      echo "timeout while waiting for: $description" >&2
      return 1
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
}

compose up -d api redis worker

pending_key="ajenda:queue:${TENANT_ID}:pending"
processing_key="ajenda:queue:${TENANT_ID}:processing"
dead_letter_key="ajenda:queue:${TENANT_ID}:dead_letter"

pending_before="$(redis_exec "LLEN $pending_key")"
processing_before="$(redis_exec "LLEN $processing_key")"
dead_before="$(redis_exec "HLEN $dead_letter_key")"

mission_resp="$(curl -fsS -X POST "$API_URL/missions" -H 'content-type: application/json' -H "x-tenant-id: $TENANT_ID" -d '{"objective":"Runtime proof","success_criteria":[{"description":"Task completes","evidence":[]}],"constraints":[],"context":{},"priority":"normal","approval_required":false,"approval_expectations":[],"scope_limits":[],"allowed_actions":[],"allowed_tools":[],"compliance_category":"operational","jurisdiction":"US-ALL"}')"
MISSION_ID="$(printf '%s' "$mission_resp" | json_get '.mission_id')"

curl -fsS -X POST "$API_URL/missions/$MISSION_ID/task-graph" -H 'content-type: application/json' -H "x-tenant-id: $TENANT_ID" -d '{"graph_status":"approved","nodes":[{"key":"collect-signals","title":"Collect signals","description":"runtime proof","depends_on":[],"intended_task_type":"echo"}],"edges":[],"metadata":{}}' >/dev/null

curl -fsS -X POST "$API_URL/missions/$MISSION_ID/materialize-graph" -H 'content-type: application/json' -H "x-tenant-id: $TENANT_ID" -d '{"materialization_status":"approved","materialization_source":"proof-script","materialization_source_version":"1.0.0","planner_provenance":{"planner_type":"deterministic"},"capability_selection_provenance":[{"node_key":"collect-signals","capability_name":"echo","selection_reason":"proof"}],"validation":{"validation_status":"valid","summary":"ok","checks":[]},"operator_review":{"status":"approved"},"generation_metadata":{"generator":"proof-script","generation_mode":"manual"},"deterministic_compilation":{"compiler_name":"proof","compiler_version":"1.0.0"}}' >/dev/null

curl -fsS -X POST "$API_URL/missions/$MISSION_ID/runtime-admission" -H 'content-type: application/json' -H "x-tenant-id: $TENANT_ID" -d '{"admission_status":"admitted","selected_nodes":[{"node_key":"collect-signals","runtime_task_type":"echo"}],"admission_notes":"proof"}' >/dev/null

curl -fsS -X POST "$API_URL/missions/$MISSION_ID/runtime-task-materialization" -H "x-tenant-id: $TENANT_ID" >/tmp/runtime_materialization.json
planned_count="$(jq '[.created_execution_task_ids[]] | length' /tmp/runtime_materialization.json)"
[[ "$planned_count" -eq "$EXPECTED_TASKS" ]] || { echo "unexpected materialized task count" >&2; exit 1; }

curl -fsS -X POST "$API_URL/missions/$MISSION_ID/runtime-queue-admission" -H "x-tenant-id: $TENANT_ID" >/tmp/runtime_queue_admission.json

poll_until "all tasks completed" "curl -fsS '$API_URL/missions/$MISSION_ID/runtime-worker-readiness' -H 'x-tenant-id: $TENANT_ID' | jq -e '.task_status_summary.completed == $EXPECTED_TASKS' >/dev/null"

readiness_json="$(curl -fsS "$API_URL/missions/$MISSION_ID/runtime-worker-readiness" -H "x-tenant-id: $TENANT_ID")"
completed="$(printf '%s' "$readiness_json" | jq '.task_status_summary.completed')"
[[ "$completed" -eq "$EXPECTED_TASKS" ]] || exit 1

lease_count="$(printf '%s' "$readiness_json" | jq '[.workers[].worker_lease_id] | map(select(. != null)) | unique | length')"
[[ "$lease_count" -eq "$EXPECTED_TASKS" ]] || { echo "worker lease uniqueness invariant failed" >&2; exit 1; }

pending_after="$(redis_exec "LLEN $pending_key")"
processing_after="$(redis_exec "LLEN $processing_key")"
dead_after="$(redis_exec "HLEN $dead_letter_key")"

[[ "$pending_after" == "$pending_before" ]] || { echo "pending queue drifted" >&2; exit 1; }
[[ "$processing_after" == "$processing_before" ]] || { echo "processing queue drifted" >&2; exit 1; }
[[ "$dead_after" == "$dead_before" ]] || { echo "dead-letter count changed" >&2; exit 1; }

echo "runtime proof passed for mission $MISSION_ID"
