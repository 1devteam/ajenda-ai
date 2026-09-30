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
  "RG-05"
  "RG-06"
  "RG-07"
  "RG-08"
  "RG-09"
  "RG-10"
  "RG-11"
  "RG-12"
  "FR-02"
  "FR-03"
  "FR-05"
)

RUNNER_BACKED_SCENARIOS=(
  "RG-01"
  "RG-02"
  "RG-03"
  "RG-04"
  "RG-05"
  "RG-06"
  "RG-07"
  "RG-10"
  "RG-12"
  "RG-08"
  "RG-09"
  "RG-11"
  "FR-02"
  "FR-03"
  "FR-05"
)

# These rows execute the governed global recovery endpoint when operators supply
# pre-seeded stale-task IDs. The runner never creates or mutates recovery state.
RECOVERY_SCENARIOS=(
  "RG-08"
  "RG-09"
  "RG-11"
  "FR-02"
  "FR-03"
  "FR-05"
)

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--group all|read-only|tenant-mutations|global-mutations] [--scenario SCENARIO_ID]...

Environment:
  AJENDA_API_URL         API base URL (default: http://localhost:8000)
  AJENDA_DB_URL          Postgres connection URL for evidence queries
  AJENDA_REDIS_URL       Redis URL for queue evidence
  AJENDA_TENANT_ID       Tenant UUID for tenant-scoped scenarios
  AJENDA_AUTH_HEADER     Authorization header value (e.g. 'Bearer ...')
  AJENDA_CLAIMED_RECOVERY_TASK_ID  seeded expired claimed task for RG-08/FR-02
  AJENDA_RUNNING_RECOVERY_TASK_ID  seeded expired running task for RG-09/FR-03
  AJENDA_RECOVERY_IDEMPOTENCY_TASK_ID seeded expired task for FR-05 (defaults to running ID)
  AJENDA_RECOVERY_STALE_TASK_ID    seeded stale task for RG-11 (defaults to claimed ID)
  AJENDA_RECOVERY_HEALTHY_TASK_ID  seeded healthy task for RG-11
  AJENDA_LOG_SOURCE      Worker log file path or docker container name
  AJENDA_VALIDATION_ENV  local|ci|shared_dev|isolated|staging (default: local)
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
    scenario_pass "$d" "$id health/readiness public"
  else
    scenario_fail "$d" "$id expected 200/200 got $s1/$s2"
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

  s3="$(AJENDA_TENANT_ID="" AJENDA_AUTH_HEADER="" api_call GET /v1/system/status "$d/system_status_missing_tenant")"

  local missing_auth_checked=0
  if [[ -n "$saved_tenant" ]]; then
    s4="$(AJENDA_TENANT_ID="$saved_tenant" AJENDA_AUTH_HEADER="" api_call GET /v1/system/status "$d/system_status_missing_auth")"
    missing_auth_checked=1
  else
    scenario_warn "$d" "$id missing-auth branch skipped because AJENDA_TENANT_ID is not set"
  fi

  if assert_status_in "$s1" 200 && \
     assert_status_in "$s2" 200 && \
     assert_status_in "$s3" 400; then
    if [[ "$missing_auth_checked" -eq 1 ]]; then
      if assert_status_in "$s4" 401; then
        scenario_pass "$d" "$id system route envelope strict checks passed"
      else
        scenario_fail "$d" "$id unexpected status codes: health=$s1 readiness=$s2 status_missing_tenant=$s3 status_missing_auth=$s4"
      fi
    else
      scenario_pass "$d" "$id system route envelope checks passed (missing-auth branch skipped: no tenant context)"
    fi
  else
    scenario_fail "$d" "$id unexpected status codes: health=$s1 readiness=$s2 status_missing_tenant=$s3"
  fi

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
    scenario_pass "$d" "$id metrics endpoint emits Prometheus text"
  else
    scenario_fail "$d" "$id expected status 200 + metrics text, got $status"
  fi
}

run_rg04_queue_admission() {
  local id="RG-04"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_SAMPLE_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_SAMPLE_TASK_ID AJENDA_TENANT_ID AJENDA_AUTH_HEADER || return 0

  local status
  status="$(api_call POST "/v1/tasks/${task_id}/queue" "$d")"
  if ! assert_status_in "$status" 200; then
    scenario_fail "$d" "$id expected 200 queue admission, got $status"
    return 0
  fi

  db_query "SELECT status FROM execution_tasks WHERE id='${task_id}';" "$d/task_status.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "queued" "$d/audit_queued.tsv" || true
  redis_cmd "$d/redis_pending.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:pending" || true

  if [[ ! -s "$d/task_status.tsv" || ! -s "$d/audit_queued.tsv" || ! -f "$d/redis_pending.txt" ]]; then
    scenario_evidence_incomplete "$d" "$id queue admission ran but required DB/audit/Redis evidence was incomplete"
    return 0
  fi

  scenario_pass "$d" "$id API+DB+audit+redis evidence captured"
}

run_rg05_invalid_envelope() {
  local id="RG-05"; local group="read-only"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local saved_tenant="${AJENDA_TENANT_ID:-}"
  local saved_auth="${AJENDA_AUTH_HEADER:-}"
  local missing_tenant_status missing_auth_status malformed_tenant_status
  local valid_tenant="${saved_tenant:-00000000-0000-0000-0000-000000000001}"

  missing_tenant_status="$(
    AJENDA_TENANT_ID="" AJENDA_AUTH_HEADER="" \
      api_call GET /v1/system/status "$d/missing_tenant"
  )"

  missing_auth_status="$(
    AJENDA_TENANT_ID="$valid_tenant" AJENDA_AUTH_HEADER="" \
      api_call GET /v1/system/status "$d/missing_auth"
  )"

  malformed_tenant_status="$(
    AJENDA_TENANT_ID="not-a-uuid" AJENDA_AUTH_HEADER="" \
      api_call GET /v1/system/status "$d/malformed_tenant"
  )"

  if assert_status_in "$missing_tenant_status" 400 && \
     assert_status_in "$missing_auth_status" 401 && \
     assert_status_in "$malformed_tenant_status" 400; then
    scenario_pass "$d" "$id invalid envelope rejection checks passed"
  else
    scenario_fail \
      "$d" \
      "$id unexpected statuses: missing_tenant=$missing_tenant_status missing_auth=$missing_auth_status malformed_tenant=$malformed_tenant_status"
  fi

  AJENDA_TENANT_ID="$saved_tenant"
  AJENDA_AUTH_HEADER="$saved_auth"
}

run_rg06_happy_execution() {
  local id="RG-06"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_SAMPLE_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_SAMPLE_TASK_ID AJENDA_TENANT_ID || return 0

  db_query "SELECT status,retry_count FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  db_query "SELECT id::text,status,holder_identity FROM worker_leases WHERE task_id='${task_id}' ORDER BY created_at DESC LIMIT 5;" "$d/lease_state.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_completed" "$d/audit_task_completed.tsv" || true
  log_evidence 'task_completed|task_dispatch_complete' "$d/worker_log.txt" || true
  redis_cmd "$d/processing_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:processing" || true

  if [[ ! -s "$d/task_state.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id missing required task state evidence: $d/task_state.tsv" missing
    return 0
  fi
  if [[ ! -s "$d/audit_task_completed.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id missing required completion audit evidence: $d/audit_task_completed.tsv" missing
    return 0
  fi
  if ! grep -Eq '^(completed)(\t|$)' "$d/task_state.tsv"; then
    scenario_fail "$d" "$id expected completed state not found in $d/task_state.tsv"
    return 0
  fi

  scenario_pass "$d" "$id happy execution evidence validated"
}

run_rg07_forced_failure() {
  local id="RG-07"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_FORCE_FAIL_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_FORCE_FAIL_TASK_ID AJENDA_TENANT_ID || return 0

  db_query "SELECT status,retry_count FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_failed" "$d/audit_task_failed.tsv" || true
  redis_cmd "$d/dead_letter_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:dead_letter" || true
  log_evidence 'task_failed|task_dispatch_handler_failed' "$d/worker_log.txt" || true

  if [[ ! -s "$d/task_state.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id missing required task state evidence: $d/task_state.tsv" missing
    return 0
  fi
  if [[ ! -s "$d/audit_task_failed.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id missing required failure audit evidence: $d/audit_task_failed.tsv" missing
    return 0
  fi
  if ! grep -Eq '^(failed|dead_lettered)(\t|$)' "$d/task_state.tsv"; then
    scenario_fail "$d" "$id expected failed/dead_lettered state not found in $d/task_state.tsv"
    return 0
  fi

  scenario_pass "$d" "$id forced failure evidence validated"
}

recovery_task_evidence() {
  local task_id="$1"
  local outdir="$2"
  mkdir -p "$outdir"
  db_query "SELECT status,retry_count FROM execution_tasks WHERE id='${task_id}';" "$outdir/task_state.tsv" || true
  db_query "SELECT id::text,status,holder_identity FROM worker_leases WHERE task_id='${task_id}' ORDER BY created_at DESC LIMIT 5;" "$outdir/lease_state.tsv" || true
  db_query "SELECT id::text,category,action,actor,created_at::text,payload_json::text FROM audit_events WHERE payload_json->>'task_id'='${task_id}' ORDER BY created_at DESC LIMIT 20;" "$outdir/task_audit.tsv" || true
  redis_cmd "$outdir/pending_payloads.txt" LRANGE "ajenda:queue:${AJENDA_TENANT_ID}:pending" 0 -1 || true
  redis_cmd "$outdir/processing_payloads.txt" LRANGE "ajenda:queue:${AJENDA_TENANT_ID}:processing" 0 -1 || true
}

recovery_endpoint_call() {
  local outdir="$1"
  local status
  status="$(api_call POST "/v1/operations/recovery" "$outdir/recovery_call")"
  printf '%s\n' "$status" > "$outdir/recovery_status.txt"
  printf '%s\n' "$status"
}

recovery_task_status() {
  local outdir="$1"
  awk -F '\t' 'NR == 1 { print $1 }' "$outdir/task_state.tsv" 2>/dev/null || true
}

recovery_lease_status() {
  local outdir="$1"
  awk -F '\t' 'NR == 1 { print $2 }' "$outdir/lease_state.tsv" 2>/dev/null || true
}

recovery_payload_count() {
  local outdir="$1"
  local file="$2"
  if [[ ! -f "$outdir/$file" ]]; then
    printf '0'
    return 0
  fi
  grep -F -c -- "$3" "$outdir/$file" || true
}

run_recovery_task_proof() {
  local id="$1"
  local task_id="$2"
  local expected_status="$3"
  local description="$4"
  local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  require_env_for_scenario "$d" AJENDA_TENANT_ID AJENDA_AUTH_HEADER AJENDA_DB_URL AJENDA_REDIS_URL || return 0
  if [[ ! "$task_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    scenario_blocked "$d" "$id requires a UUID-shaped seeded task ID"
    return 0
  fi

  recovery_task_evidence "$task_id" "$d/before"
  local status
  status="$(recovery_endpoint_call "$d")"
  recovery_task_evidence "$task_id" "$d/after"

  if ! assert_status_in "$status" 200; then
    scenario_fail "$d" "$id recovery endpoint expected HTTP 200, got $status"
    return 0
  fi
  if [[ ! -s "$d/before/task_state.tsv" || ! -s "$d/before/lease_state.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id missing pre-recovery task or lease evidence"
    return 0
  fi
  local initial_status initial_lease
  initial_status="$(recovery_task_status "$d/before")"
  initial_lease="$(recovery_lease_status "$d/before")"
  if [[ "$initial_status" != "claimed" && "$initial_status" != "running" ]] || \
     [[ "$initial_lease" != "claimed" && "$initial_lease" != "active" ]]; then
    scenario_fail "$d" "$id seeded task was not stale-recovery eligible: status=${initial_status:-missing} lease=${initial_lease:-missing}"
    return 0
  fi
  if [[ ! -s "$d/after/task_state.tsv" || ! -s "$d/after/lease_state.tsv" || ! -s "$d/after/task_audit.tsv" || ! -f "$d/after/pending_payloads.txt" || ! -f "$d/after/processing_payloads.txt" ]]; then
    scenario_evidence_incomplete "$d" "$id recovery ran but required DB/audit/Redis evidence was incomplete"
    return 0
  fi

  local final_status final_lease pending_count processing_count
  final_status="$(recovery_task_status "$d/after")"
  final_lease="$(recovery_lease_status "$d/after")"
  pending_count="$(recovery_payload_count "$d/after" pending_payloads.txt "$task_id")"
  processing_count="$(recovery_payload_count "$d/after" processing_payloads.txt "$task_id")"
  if [[ "$final_status" != "$expected_status" || "$final_lease" != "expired" ]]; then
    scenario_fail "$d" "$id $description expected status=$expected_status and lease=expired, got status=${final_status:-missing} lease=${final_lease:-missing}"
    return 0
  fi
  if [[ "$expected_status" == "queued" && "$pending_count" -ne 1 ]] || [[ "$processing_count" -ne 0 ]]; then
    scenario_fail "$d" "$id queue reconciliation expected pending=1 and processing=0, got pending=$pending_count processing=$processing_count"
    return 0
  fi
  scenario_pass "$d" "$id $description validated through governed recovery API, DB, audit, and Redis"
}

run_rg08_claimed_recovery() {
  run_recovery_task_proof "RG-08" "${AJENDA_CLAIMED_RECOVERY_TASK_ID:-}" queued "stale claimed lease requeued safely"
}

run_rg09_running_recovery() {
  run_recovery_task_proof "RG-09" "${AJENDA_RUNNING_RECOVERY_TASK_ID:-}" queued "stale running lease requeued with reconciled queue state"
}

run_fr02_claimed_recovery() {
  run_recovery_task_proof "FR-02" "${AJENDA_CLAIMED_RECOVERY_TASK_ID:-}" queued "claimed lease recovery invariant"
}

run_fr03_running_recovery() {
  run_recovery_task_proof "FR-03" "${AJENDA_RUNNING_RECOVERY_TASK_ID:-}" queued "running lease recovery invariant"
}

run_fr05_recovery_idempotency() {
  local id="FR-05"; local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"
  local task_id="${AJENDA_RECOVERY_IDEMPOTENCY_TASK_ID:-${AJENDA_RUNNING_RECOVERY_TASK_ID:-}}"
  require_env_for_scenario "$d" AJENDA_TENANT_ID AJENDA_AUTH_HEADER AJENDA_DB_URL AJENDA_REDIS_URL || return 0
  if [[ ! "$task_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    scenario_blocked "$d" "$id requires a UUID-shaped seeded task ID"
    return 0
  fi
  local first_api_status second_api_status
  first_api_status="$(recovery_endpoint_call "$d/first")"
  recovery_task_evidence "$task_id" "$d/first"
  second_api_status="$(recovery_endpoint_call "$d/second")"
  recovery_task_evidence "$task_id" "$d/second"
  if ! assert_status_in "$first_api_status" 200 || ! assert_status_in "$second_api_status" 200 || \
     [[ ! -s "$d/first/task_state.tsv" || ! -s "$d/second/task_state.tsv" || ! -f "$d/first/pending_payloads.txt" || ! -f "$d/second/pending_payloads.txt" ]]; then
    scenario_evidence_incomplete "$d" "$id recovery idempotency ran but required task/queue evidence was incomplete"
    return 0
  fi
  local first_status second_status first_pending second_pending
  first_status="$(recovery_task_status "$d/first")"
  second_status="$(recovery_task_status "$d/second")"
  first_pending="$(recovery_payload_count "$d/first" pending_payloads.txt "$task_id")"
  second_pending="$(recovery_payload_count "$d/second" pending_payloads.txt "$task_id")"
  if [[ "$first_status" != "$second_status" || "$first_pending" -ne "$second_pending" ]]; then
    scenario_fail "$d" "$id repeated recovery changed task/queue projection: first status=$first_status pending=$first_pending; second status=$second_status pending=$second_pending"
    return 0
  fi
  scenario_pass "$d" "$id repeated recovery was stable without duplicate queue projection"
}

run_rg10_dead_letter_retry_legality() {
  local id="RG-10"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_DEAD_LETTER_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_DEAD_LETTER_TASK_ID AJENDA_TENANT_ID AJENDA_AUTH_HEADER || return 0

  local status
  status="$(api_call POST "/v1/operations/dead-letter/${task_id}/retry" "$d")"
  db_query "SELECT status FROM execution_tasks WHERE id='${task_id}';" "$d/task_status.tsv" || true
  if assert_status_in "$status" 400; then
    if [[ ! -s "$d/task_status.tsv" ]]; then
      scenario_evidence_incomplete "$d" "$id illegal retry was rejected but DB evidence was incomplete"
    else
      scenario_pass "$d" "$id illegal transition correctly rejected"
    fi
  else
    scenario_fail "$d" "$id expected HTTP 400, got $status"
  fi
}

run_rg11_recovery_safety() {
  local id="RG-11"; local group="global-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"
  local stale_id="${AJENDA_RECOVERY_STALE_TASK_ID:-${AJENDA_CLAIMED_RECOVERY_TASK_ID:-}}"
  local healthy_id="${AJENDA_RECOVERY_HEALTHY_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_TENANT_ID AJENDA_AUTH_HEADER AJENDA_DB_URL AJENDA_REDIS_URL || return 0
  if [[ ! "$stale_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ || ! "$healthy_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    scenario_blocked "$d" "$id requires UUID-shaped stale and healthy seeded task IDs"
    return 0
  fi
  db_query "SELECT id::text,status,retry_count FROM execution_tasks WHERE id IN ('${stale_id}','${healthy_id}') ORDER BY id;" "$d/before_tasks.tsv" || true
  db_query "SELECT task_id::text,status,holder_identity FROM worker_leases WHERE task_id IN ('${stale_id}','${healthy_id}') ORDER BY task_id,created_at DESC;" "$d/before_leases.tsv" || true
  local recovery_status
  recovery_status="$(recovery_endpoint_call "$d")"
  db_query "SELECT id::text,status,retry_count FROM execution_tasks WHERE id IN ('${stale_id}','${healthy_id}') ORDER BY id;" "$d/after_tasks.tsv" || true
  db_query "SELECT task_id::text,status,holder_identity FROM worker_leases WHERE task_id IN ('${stale_id}','${healthy_id}') ORDER BY task_id,created_at DESC;" "$d/after_leases.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "global_recovery_completed" "$d/recovery_audit.tsv" || true
  if ! assert_status_in "$recovery_status" 200; then
    scenario_fail "$d" "$id recovery endpoint expected HTTP 200, got $recovery_status"
    return 0
  fi
  if [[ ! -s "$d/before_tasks.tsv" || ! -s "$d/before_leases.tsv" || ! -s "$d/after_tasks.tsv" || ! -s "$d/after_leases.tsv" || ! -s "$d/recovery_audit.tsv" ]]; then
    scenario_evidence_incomplete "$d" "$id recovery safety ran but before/after task, lease, or audit evidence was incomplete"
    return 0
  fi
  local healthy_before healthy_after
  local stale_before stale_after stale_lease_after
  stale_before="$(awk -F '\t' -v id="$stale_id" '$1 == id { print $2 "\t" $3; exit }' "$d/before_tasks.tsv")"
  stale_after="$(awk -F '\t' -v id="$stale_id" '$1 == id { print $2 "\t" $3; exit }' "$d/after_tasks.tsv")"
  stale_lease_after="$(awk -F '\t' -v id="$stale_id" '$1 == id { print $2; exit }' "$d/after_leases.tsv")"
  if [[ -z "$stale_before" || "$stale_before" == "$stale_after" || "$stale_lease_after" != "expired" ]]; then
    scenario_fail "$d" "$id stale task did not produce an observable recovery transition: before=${stale_before:-missing} after=${stale_after:-missing} lease=${stale_lease_after:-missing}"
    return 0
  fi
  healthy_before="$(awk -F '\t' -v id="$healthy_id" '$1 == id { print $2 "\t" $3; exit }' "$d/before_tasks.tsv")"
  healthy_after="$(awk -F '\t' -v id="$healthy_id" '$1 == id { print $2 "\t" $3; exit }' "$d/after_tasks.tsv")"
  if [[ -z "$healthy_before" || "$healthy_before" != "$healthy_after" ]]; then
    scenario_fail "$d" "$id healthy task changed during stale recovery: before=${healthy_before:-missing} after=${healthy_after:-missing}"
    return 0
  fi
  scenario_pass "$d" "$id stale recovery changed only the seeded stale work; healthy work remained unchanged"
}

run_rg12_pending_review() {
  local id="RG-12"; local group="tenant-mutation"
  scenario_enabled "$id" "$group" || return 0
  local d; d="$(scenario_dir "$id")"

  local task_id="${AJENDA_PENDING_REVIEW_TASK_ID:-}"
  require_env_for_scenario "$d" AJENDA_PENDING_REVIEW_TASK_ID AJENDA_TENANT_ID AJENDA_AUTH_HEADER || return 0

  local status
  status="$(api_call POST "/v1/tasks/${task_id}/queue" "$d")"
  db_query "SELECT status,requires_human_review FROM execution_tasks WHERE id='${task_id}';" "$d/task_state.tsv" || true
  db_query "SELECT event_type,decision FROM governance_events WHERE payload_json->>'task_id'='${task_id}' ORDER BY created_at DESC LIMIT 10;" "$d/governance.tsv" || true
  audit_lookup "$AJENDA_TENANT_ID" "task_pending_review" "$d/audit_pending_review.tsv" || true
  redis_cmd "$d/pending_len.txt" LLEN "ajenda:queue:${AJENDA_TENANT_ID}:pending" || true
  if assert_status_in "$status" 400; then
    if [[ ! -s "$d/task_state.tsv" || ! -s "$d/governance.tsv" || ! -s "$d/audit_pending_review.tsv" || ! -f "$d/pending_len.txt" ]]; then
      scenario_evidence_incomplete "$d" "$id pending-review denial ran but required evidence was incomplete"
    else
      scenario_pass "$d" "$id pending_review policy gate evidenced"
    fi
  else
    scenario_fail "$d" "$id expected 400 policy denial, got $status"
  fi
}

main() {
  validate_environment

  run_rg01_health
  run_rg02_system_status
  run_rg03_metrics
  run_rg04_queue_admission
  run_rg05_invalid_envelope
  run_rg06_happy_execution
  run_rg07_forced_failure
  run_rg08_claimed_recovery
  run_rg09_running_recovery
  run_fr02_claimed_recovery
  run_fr03_running_recovery
  run_fr05_recovery_idempotency
  run_rg10_dead_letter_retry_legality
  run_rg11_recovery_safety
  run_rg12_pending_review

  print_summary
}

main "$@"
