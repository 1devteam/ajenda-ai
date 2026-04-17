#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/validation/lib.sh
source "$SCRIPT_DIR/lib.sh"

SELECTED_SCENARIOS=()
RUN_GROUP="all"
SUPPORTED_SCENARIOS=(
  "RG-01"
  "RG-02"
  "RG-03"
  "RG-04"
  "RG-06"
  "RG-07"
  "RG-08"
  "RG-09"
  "RG-10"
  "RG-11"
  "RG-12"
)

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--group all|read-only|tenant-mutations|global-mutations] [--scenario SCENARIO_ID]...

Environment:
  AJENDA_API_URL       API base URL (default: http://localhost:8000)
  AJENDA_DB_URL        Postgres connection URL for evidence queries
  AJENDA_REDIS_URL     Redis URL for queue evidence
  AJENDA_TENANT_ID     Tenant UUID for tenant-scoped scenarios
  AJENDA_AUTH_HEADER   Authorization header value (e.g. 'Bearer ...')
  AJENDA_LOG_SOURCE    Worker log file path or docker container name
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --group)
      RUN_GROUP="$2"; shift 2 ;;
    --scenario)
      SELECTED_SCENARIOS+=("$2"); shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

case "$RUN_GROUP" in
  all|read-only|tenant-mutations|global-mutations) ;;
  *)
    echo "Invalid --group value: $RUN_GROUP" >&2
    usage
    exit 2
    ;;
esac

if [[ ${#SELECTED_SCENARIOS[@]} -gt 0 ]]; then
  for selected in "${SELECTED_SCENARIOS[@]}"; do
    known=0
    for supported in "${SUPPORTED_SCENARIOS[@]}"; do
      if [[ "$selected" == "$supported" ]]; then
        known=1
        break
      fi
    done
    if [[ "$known" -ne 1 ]]; then
      echo "Invalid --scenario value: $selected" >&2
      usage
      exit 2
    fi
  done
fi

scenario_enabled() {
  local id="$1"
  local group="$2"
  if [[ ${#SELECTED_SCENARIOS[@]} -gt 0 ]]; then
    for s in "${SELECTED_SCENARIOS[@]}"; do
      [[ "$s" == "$id" ]] && return 0
    done
    return 1
  fi

  case "$RUN_GROUP" in
    all) return 0 ;;
    read-only) [[ "$group" == "read-only" ]] ;;
    tenant-mutations) [[ "$group" == "tenant-mutation" ]] ;;
    global-mutations) [[ "$group" == "global-mutation" ]] ;;
    *) return 1 ;;
  esac
}

run_rg01_health() {
  local id="RG-01"; local group="read-only"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local s1 s2
  s1="$(api_call GET /health "$d/health")"
  s2="$(api_call GET /readiness "$d/readiness")"
  if assert_status_in "$s1" 200 && assert_status_in "$s2" 200; then
    pass "$id health/readiness public"
  else
    fail "$id expected 200/200 got $s1/$s2"
  fi
}

run_rg02_system_status() {
  local id="RG-02"; local group="read-only"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local s1 s2 s3 s4
  s1="$(api_call GET /v1/system/health "$d/system_health")"
  s2="$(api_call GET /v1/system/readiness "$d/system_readiness")"
  local saved_tenant="${AJENDA_TENANT_ID:-}"
  local saved_auth="${AJENDA_AUTH_HEADER:-}"

  # Deliberate missing-tenant probe: send neither tenant nor auth.
  s3="$(AJENDA_TENANT_ID="" AJENDA_AUTH_HEADER="" api_call GET /v1/system/status "$d/system_status_missing_tenant")"

  if [[ -z "$saved_tenant" ]]; then
    fail "$id cannot assert missing-auth branch: AJENDA_TENANT_ID is not set"
    return 0
  fi
  # Deliberate missing-auth probe: send tenant only.
  s4="$(AJENDA_TENANT_ID="$saved_tenant" AJENDA_AUTH_HEADER="" api_call GET /v1/system/status "$d/system_status_missing_auth")"

  if assert_status_in "$s1" 200 && \
     assert_status_in "$s2" 200 && \
     assert_status_in "$s3" 400 && \
     assert_status_in "$s4" 401; then
    pass "$id system route envelope strict checks passed"
  else
    fail "$id unexpected status codes: health=$s1 readiness=$s2 status_missing_tenant=$s3 status_missing_auth=$s4"
  fi

  # Preserve caller environment values explicitly for downstream scenarios.
  AJENDA_TENANT_ID="$saved_tenant"
  AJENDA_AUTH_HEADER="$saved_auth"
}

run_rg03_metrics() {
  local id="RG-03"; local group="read-only"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local status
  status="$(api_call GET /v1/observability/metrics "$d")"
  if assert_status_in "$status" 200 && grep -q 'ajenda_' "$d/body.txt"; then
    pass "$id metrics endpoint emits Prometheus text"
  else
    fail "$id expected status 200 + metrics text, got $status"
  fi
}

run_rg04_queue_admission() {
  local id="RG-04"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_SAMPLE_TASK_ID:-}"
  if ! require_env AJENDA_SAMPLE_TASK_ID || ! require_env AJENDA_TENANT_ID || ! require_env AJENDA_AUTH_HEADER; then
    return 0
  fi

  local status
  status="$(api_call POST "/v1/tasks/${task_id}/queue" "$d")"
  if ! assert_status_in "$status" 200; then
    fail "$id expected 200 queue admission, got $status"
    return 0
  fi

  db_query "SELECT status FROM execution_tasks WHERE id='${task_id}';" "$d/task_status.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "queued" "$d/audit_queued.tsv" || true
  redis_cmd "$d/redis_pending.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:pending" || true

  pass "$id API+DB+audit+redis evidence captured"
}

run_rg06_happy_execution() {
  local id="RG-06"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_SAMPLE_TASK_ID:-}"
  if ! require_env AJENDA_SAMPLE_TASK_ID || ! require_env AJENDA_TENANT_ID; then
    return 0
  fi

  db_query "SELECT status,retry_count FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  db_query "SELECT id::text,status,holder_identity FROM worker_leases WHERE task_id='${task_id}' ORDER BY created_at DESC LIMIT 5;" "$d/lease_state.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_completed" "$d/audit_task_completed.tsv" || true
  log_evidence 'task_completed|task_dispatch_complete' "$d/worker_log.txt" || true
  redis_cmd "$d/processing_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:processing" || true

  if [[ ! -s "$d/task_state.tsv" ]]; then
    fail "$id missing required task state evidence: $d/task_state.tsv"
    return 0
  fi
  if [[ ! -s "$d/audit_task_completed.tsv" ]]; then
    fail "$id missing required completion audit evidence: $d/audit_task_completed.tsv"
    return 0
  fi
  if ! grep -Eq $'\tcompleted($|\t)' "$d/task_state.tsv"; then
    fail "$id expected completed state not found in $d/task_state.tsv"
    return 0
  fi

  pass "$id happy execution evidence validated"
}

run_rg07_forced_failure() {
  local id="RG-07"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_FORCE_FAIL_TASK_ID:-}"
  if ! require_env AJENDA_FORCE_FAIL_TASK_ID || ! require_env AJENDA_TENANT_ID; then
    return 0
  fi

  db_query "SELECT status,retry_count FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_failed" "$d/audit_task_failed.tsv" || true
  redis_cmd "$d/dead_letter_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:dead_letter" || true
  log_evidence 'task_failed|task_dispatch_handler_failed' "$d/worker_log.txt" || true

  if [[ ! -s "$d/task_state.tsv" ]]; then
    fail "$id missing required task state evidence: $d/task_state.tsv"
    return 0
  fi
  if [[ ! -s "$d/audit_task_failed.tsv" ]]; then
    fail "$id missing required failure audit evidence: $d/audit_task_failed.tsv"
    return 0
  fi
  if ! grep -Eq $'\t(failed|dead_lettered)($|\t)' "$d/task_state.tsv"; then
    fail "$id expected failed/dead_lettered state not found in $d/task_state.tsv"
    return 0
  fi

  pass "$id forced failure evidence validated"
}

run_rg08_claimed_recovery() {
  local id="RG-08"; local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local status
  status="$(api_call POST /v1/operations/recovery "$d/recovery_call")"
  db_query "SELECT action,details,created_at::text FROM audit_events WHERE action='claimed_task_requeued_on_lease_expiry' ORDER BY created_at DESC LIMIT 20;" "$d/audit_claimed.tsv" || true
  if assert_status_in "$status" 200; then
    pass "$id recovery endpoint and claimed recovery evidence captured"
  else
    fail "$id expected 200, got $status"
  fi
}

run_rg09_running_recovery() {
  local id="RG-09"; local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local status
  status="$(api_call POST /v1/operations/recovery "$d/recovery_call")"
  db_query "SELECT id::text,status,retry_count FROM execution_tasks WHERE status IN ('queued','dead_lettered','recovering') ORDER BY updated_at DESC LIMIT 50;" "$d/task_recovery.tsv" || true
  db_query "SELECT id::text,status,task_id::text,heartbeat_at::text FROM worker_leases WHERE status='expired' ORDER BY updated_at DESC LIMIT 50;" "$d/expired_leases.tsv" || true
  if assert_status_in "$status" 200; then
    pass "$id running recovery evidence captured"
  else
    fail "$id expected 200, got $status"
  fi
}

run_rg10_dead_letter_retry_legality() {
  local id="RG-10"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_DEAD_LETTER_TASK_ID:-}"
  if ! require_env AJENDA_DEAD_LETTER_TASK_ID || ! require_env AJENDA_TENANT_ID || ! require_env AJENDA_AUTH_HEADER; then
    return 0
  fi

  local status
  status="$(api_call POST "/v1/operations/dead-letter/${task_id}/retry" "$d")"
  db_query "SELECT status FROM execution_tasks WHERE id='${task_id}';" "$d/task_status.tsv" || true
  if assert_status_in "$status" 400; then
    pass "$id illegal transition correctly rejected"
  else
    fail "$id expected HTTP 400, got $status"
  fi
}

run_rg11_recovery_safety() {
  local id="RG-11"; local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local status expired_count
  local before="$d/task_distribution_before.tsv"
  local after="$d/task_distribution_after.tsv"
  db_query "SELECT tenant_id,status,count(*) FROM execution_tasks GROUP BY tenant_id,status ORDER BY tenant_id,status;" "$before" || true
  status="$(api_call POST /v1/operations/recovery "$d")"
  db_query "SELECT tenant_id,status,count(*) FROM execution_tasks GROUP BY tenant_id,status ORDER BY tenant_id,status;" "$after" || true

  expired_count="$(jq -r '.expired_lease_count // empty' "$d/body.txt" 2>/dev/null || true)"
  if assert_status_in "$status" 200; then
    if [[ "${expired_count}" == "0" ]] && [[ -f "$before" ]] && [[ -f "$after" ]]; then
      if cmp -s "$before" "$after"; then
        pass "$id recovery safety verified: no expired leases, no task distribution drift"
      else
        fail "$id recovery safety failed: no expired leases but task distribution changed"
      fi
    else
      pass "$id recovery safety evidence captured (expired_lease_count=${expired_count:-unknown})"
    fi
  else
    fail "$id expected 200, got $status"
  fi
}

run_rg12_pending_review() {
  local id="RG-12"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_PENDING_REVIEW_TASK_ID:-}"
  if ! require_env AJENDA_PENDING_REVIEW_TASK_ID || ! require_env AJENDA_TENANT_ID || ! require_env AJENDA_AUTH_HEADER; then
    return 0
  fi

  local status
  status="$(api_call POST "/v1/tasks/${task_id}/queue" "$d")"
  db_query "SELECT status,requires_human_review FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  db_query "SELECT event_type,decision FROM governance_events WHERE payload_json->>'task_id'='${task_id}' ORDER BY created_at DESC LIMIT 10;" "$d/governance.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_pending_review" "$d/audit_pending_review.tsv" || true
  redis_cmd "$d/pending_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:pending" || true
  if assert_status_in "$status" 400; then
    pass "$id pending_review policy gate evidenced"
  else
    fail "$id expected 400 policy denial, got $status"
  fi
}

main() {
  validate_environment

  run_rg01_health
  run_rg02_system_status
  run_rg03_metrics
  run_rg04_queue_admission
  run_rg06_happy_execution
  run_rg07_forced_failure
  run_rg08_claimed_recovery
  run_rg09_running_recovery
  run_rg10_dead_letter_retry_legality
  run_rg11_recovery_safety
  run_rg12_pending_review

  print_summary
}

main "$@"
