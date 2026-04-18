#!/usr/bin/env bash
set -euo pipefail

VALIDATION_ROOT="${VALIDATION_ROOT:-artifacts/validation}"
VALIDATION_TS="${VALIDATION_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$VALIDATION_ROOT/$VALIDATION_TS}"
RESULTS_TSV="$ARTIFACT_DIR/scenario_results.tsv"
SUMMARY_JSON="$ARTIFACT_DIR/summary.json"

AJENDA_API_URL="${AJENDA_API_URL:-http://localhost:8000}"
AJENDA_DB_URL="${AJENDA_DB_URL:-}"
AJENDA_REDIS_URL="${AJENDA_REDIS_URL:-}"
AJENDA_LOG_SOURCE="${AJENDA_LOG_SOURCE:-}"
AJENDA_TENANT_ID="${AJENDA_TENANT_ID:-}"
AJENDA_AUTH_HEADER="${AJENDA_AUTH_HEADER:-}"
AJENDA_VALIDATION_ENV="${AJENDA_VALIDATION_ENV:-local}"

mkdir -p "$ARTIFACT_DIR"
printf 'scenario_id\trun_outcome\tevidence_status\tvalidation_env\tartifact_path\tnotes\n' > "$RESULTS_TSV"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
SKIP_COUNT=0
BLOCKED_COUNT=0
INVALID_RUN_COUNT=0
ENVIRONMENT_INELIGIBLE_COUNT=0
EVIDENCE_INCOMPLETE_COUNT=0

log() { printf '%s\n' "$*"; }

_increment_result_counter() {
  local outcome="$1"
  case "$outcome" in
    pass) PASS_COUNT=$((PASS_COUNT + 1)) ;;
    fail) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
    warn) WARN_COUNT=$((WARN_COUNT + 1)) ;;
    skip) SKIP_COUNT=$((SKIP_COUNT + 1)) ;;
    blocked) BLOCKED_COUNT=$((BLOCKED_COUNT + 1)) ;;
    invalid_run) INVALID_RUN_COUNT=$((INVALID_RUN_COUNT + 1)) ;;
    environment_ineligible) ENVIRONMENT_INELIGIBLE_COUNT=$((ENVIRONMENT_INELIGIBLE_COUNT + 1)) ;;
    evidence_incomplete) EVIDENCE_INCOMPLETE_COUNT=$((EVIDENCE_INCOMPLETE_COUNT + 1)) ;;
  esac
}

_result_prefix() {
  local outcome="$1"
  case "$outcome" in
    pass) printf '[PASS]' ;;
    fail) printf '[FAIL]' ;;
    warn) printf '[WARN]' ;;
    skip) printf '[SKIP]' ;;
    blocked) printf '[BLOCKED]' ;;
    invalid_run) printf '[INVALID_RUN]' ;;
    environment_ineligible) printf '[ENVIRONMENT_INELIGIBLE]' ;;
    evidence_incomplete) printf '[EVIDENCE_INCOMPLETE]' ;;
    *) printf '[INFO]' ;;
  esac
}

write_result_metadata() {
  local outdir="$1"
  local outcome="$2"
  local evidence_status="$3"
  local message="$4"
  mkdir -p "$outdir"
  printf '%s\n' "$outcome" > "$outdir/run_outcome.txt"
  printf '%s\n' "$evidence_status" > "$outdir/evidence_status.txt"
  printf '%s\n' "$message" > "$outdir/notes.txt"
  printf '%s\n' "$AJENDA_VALIDATION_ENV" > "$outdir/validation_env.txt"
}

record_scenario_result() {
  local outdir="$1"
  local outcome="$2"
  local evidence_status="$3"
  local message="$4"
  local scenario_id
  scenario_id="$(basename "$outdir")"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$scenario_id" \
    "$outcome" \
    "$evidence_status" \
    "$AJENDA_VALIDATION_ENV" \
    "$outdir" \
    "$message" >> "$RESULTS_TSV"
}

scenario_result() {
  local outcome="$1"
  local evidence_status="$2"
  local outdir="$3"
  local message="$4"
  _increment_result_counter "$outcome"
  log "$(_result_prefix "$outcome") $message"
  write_result_metadata "$outdir" "$outcome" "$evidence_status" "$message"
  record_scenario_result "$outdir" "$outcome" "$evidence_status" "$message"
}

pass() { _increment_result_counter pass; log "[PASS] $*"; }
fail() { _increment_result_counter fail; log "[FAIL] $*"; }
warn() { _increment_result_counter warn; log "[WARN] $*"; }

scenario_pass() { scenario_result pass complete "$1" "$2"; }
scenario_fail() { scenario_result fail complete "$1" "$2"; }
scenario_warn() { scenario_result warn partial "$1" "$2"; }
scenario_skip() { scenario_result skip missing "$1" "$2"; }
scenario_blocked() { scenario_result blocked missing "$1" "$2"; }
scenario_invalid_run() { scenario_result invalid_run missing "$1" "$2"; }
scenario_environment_ineligible() { scenario_result environment_ineligible missing "$1" "$2"; }
scenario_evidence_incomplete() {
  local outdir="$1"
  local message="$2"
  local evidence_status="${3:-partial}"
  scenario_result evidence_incomplete "$evidence_status" "$outdir" "$message"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    warn "missing command: $cmd"
    return 1
  fi
  return 0
}

require_env() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    fail "missing required environment variable: ${var_name}"
    return 1
  fi
  return 0
}

require_env_for_scenario() {
  local outdir="$1"
  shift
  local missing_vars=()
  local var_name
  for var_name in "$@"; do
    if [[ -z "${!var_name:-}" ]]; then
      missing_vars+=("$var_name")
    fi
  done
  if [[ ${#missing_vars[@]} -gt 0 ]]; then
    scenario_blocked "$outdir" "missing required environment variable(s): ${missing_vars[*]}"
    return 1
  fi
  return 0
}

require_validation_env_for_scenario() {
  local outdir="$1"
  shift
  local allowed_envs=("$@")
  local allowed
  for allowed in "${allowed_envs[@]}"; do
    if [[ "$AJENDA_VALIDATION_ENV" == "$allowed" ]]; then
      return 0
    fi
  done
  scenario_environment_ineligible \
    "$outdir" \
    "scenario requires validation environment in [${allowed_envs[*]}], got ${AJENDA_VALIDATION_ENV}"
  return 1
}

validate_environment() {
  log "Validation artifact dir: $ARTIFACT_DIR"
  log "Validation environment: $AJENDA_VALIDATION_ENV"
  require_cmd curl || true
  require_cmd jq || true
  require_cmd python || true

  if [[ -z "${AJENDA_API_URL}" ]]; then
    fail "AJENDA_API_URL not set"
  fi
}

scenario_dir() {
  local scenario_id="$1"
  local d="$ARTIFACT_DIR/$scenario_id"
  mkdir -p "$d"
  printf '%s' "$d"
}

api_call() {
  local method="$1"; shift
  local path="$1"; shift
  local outdir="$1"; shift

  mkdir -p "$outdir"

  local body="${1:-}"
  local headers_file="$outdir/headers.txt"
  local body_file="$outdir/body.txt"
  local status_file="$outdir/status.txt"

  local curl_args=(-sS -X "$method" "$AJENDA_API_URL$path" -D "$headers_file" -o "$body_file" -w '%{http_code}')
  if [[ -n "$AJENDA_TENANT_ID" ]]; then
    curl_args+=( -H "X-Tenant-Id: $AJENDA_TENANT_ID" )
  fi
  if [[ -n "$AJENDA_AUTH_HEADER" ]]; then
    curl_args+=( -H "Authorization: $AJENDA_AUTH_HEADER" )
  fi
  if [[ -n "$body" ]]; then
    curl_args+=( -H 'Content-Type: application/json' --data "$body" )
  fi

  local status
  status=$(curl "${curl_args[@]}" || true)
  printf '%s' "$status" > "$status_file"
  printf '%s' "$status"
}

db_query() {
  local sql="$1"
  local out_file="$2"
  if [[ -z "${AJENDA_DB_URL}" ]]; then
    warn "AJENDA_DB_URL not set; skipping DB query"
    return 1
  fi
  if ! require_cmd psql; then
    return 1
  fi
  psql "$AJENDA_DB_URL" -v ON_ERROR_STOP=1 -At -F $'\t' -c "$sql" > "$out_file"
}

redis_cmd() {
  local out_file="$1"; shift
  if [[ -z "${AJENDA_REDIS_URL}" ]]; then
    warn "AJENDA_REDIS_URL not set; skipping redis check"
    return 1
  fi
  if ! require_cmd redis-cli; then
    return 1
  fi
  redis-cli -u "$AJENDA_REDIS_URL" "$@" > "$out_file"
}

audit_lookup() {
  local tenant_id="$1"
  local action="$2"
  local out_file="$3"
  db_query "SELECT id::text, category, action, actor, created_at::text FROM audit_events WHERE tenant_id='${tenant_id}' AND action='${action}' ORDER BY created_at DESC LIMIT 20;" "$out_file"
}

log_evidence() {
  local pattern="$1"
  local out_file="$2"
  if [[ -z "$AJENDA_LOG_SOURCE" ]]; then
    warn "AJENDA_LOG_SOURCE not set; skipping log evidence"
    return 1
  fi
  if [[ -f "$AJENDA_LOG_SOURCE" ]]; then
    grep -n "$pattern" "$AJENDA_LOG_SOURCE" > "$out_file" || true
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    docker logs "$AJENDA_LOG_SOURCE" 2>&1 | grep -n "$pattern" > "$out_file" || true
    return 0
  fi
  warn "AJENDA_LOG_SOURCE is neither file nor docker container"
  return 1
}

assert_status_in() {
  local status="$1"; shift
  local expected=($*)
  for x in "${expected[@]}"; do
    if [[ "$status" == "$x" ]]; then
      return 0
    fi
  done
  return 1
}

write_summary_manifest() {
  cat > "$SUMMARY_JSON" <<EOF
{
  "validation_ts": "$VALIDATION_TS",
  "artifact_dir": "$ARTIFACT_DIR",
  "validation_env": "$AJENDA_VALIDATION_ENV",
  "counts": {
    "pass": $PASS_COUNT,
    "fail": $FAIL_COUNT,
    "warn": $WARN_COUNT,
    "skip": $SKIP_COUNT,
    "blocked": $BLOCKED_COUNT,
    "invalid_run": $INVALID_RUN_COUNT,
    "environment_ineligible": $ENVIRONMENT_INELIGIBLE_COUNT,
    "evidence_incomplete": $EVIDENCE_INCOMPLETE_COUNT
  },
  "scenario_results_tsv": "$RESULTS_TSV"
}
EOF
}

print_summary() {
  write_summary_manifest
  log "----"
  log "Validation summary: pass=$PASS_COUNT fail=$FAIL_COUNT warn=$WARN_COUNT skip=$SKIP_COUNT blocked=$BLOCKED_COUNT invalid_run=$INVALID_RUN_COUNT environment_ineligible=$ENVIRONMENT_INELIGIBLE_COUNT evidence_incomplete=$EVIDENCE_INCOMPLETE_COUNT"
  log "Artifacts: $ARTIFACT_DIR"
  log "Scenario ledger: $RESULTS_TSV"
  log "Run manifest: $SUMMARY_JSON"
  if [[ "$FAIL_COUNT" -gt 0 || "$BLOCKED_COUNT" -gt 0 || "$INVALID_RUN_COUNT" -gt 0 || "$ENVIRONMENT_INELIGIBLE_COUNT" -gt 0 || "$EVIDENCE_INCOMPLETE_COUNT" -gt 0 ]]; then
    return 1
  fi
  return 0
}
