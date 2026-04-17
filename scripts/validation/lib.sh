#!/usr/bin/env bash
set -euo pipefail

VALIDATION_ROOT="${VALIDATION_ROOT:-artifacts/validation}"
VALIDATION_TS="${VALIDATION_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"
ARTIFACT_DIR="${ARTIFACT_DIR:-$VALIDATION_ROOT/$VALIDATION_TS}"

AJENDA_API_URL="${AJENDA_API_URL:-http://localhost:8000}"
AJENDA_DB_URL="${AJENDA_DB_URL:-}"
AJENDA_REDIS_URL="${AJENDA_REDIS_URL:-}"
AJENDA_LOG_SOURCE="${AJENDA_LOG_SOURCE:-}"
AJENDA_TENANT_ID="${AJENDA_TENANT_ID:-}"
AJENDA_AUTH_HEADER="${AJENDA_AUTH_HEADER:-}"

mkdir -p "$ARTIFACT_DIR"

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

log() { printf '%s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; WARN_COUNT=$((WARN_COUNT + 1)); }
pass() { printf '[PASS] %s\n' "$*"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { printf '[FAIL] %s\n' "$*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    warn "missing command: $cmd"
    return 1
  fi
  return 0
}

validate_environment() {
  log "Validation artifact dir: $ARTIFACT_DIR"
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

print_summary() {
  log "----"
  log "Validation summary: pass=$PASS_COUNT fail=$FAIL_COUNT warn=$WARN_COUNT"
  log "Artifacts: $ARTIFACT_DIR"
  if [[ "$FAIL_COUNT" -gt 0 ]]; then
    return 1
  fi
  return 0
}
