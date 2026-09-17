#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
COMPOSE_PROJECT_NAME="${AJENDA_PROOF_COMPOSE_PROJECT_NAME:-ajenda-ai}"
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
  docker compose -p "$COMPOSE_PROJECT_NAME" --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"
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

log "stopping prior compose services while preserving persistent database volumes"
# A runtime proof must not destroy operator sign-ins, tenants, missions, or
# artifacts.  Environment rotation is handled by migrations and service
# restart; volume deletion belongs to an explicit disposable test command.
compose down --remove-orphans >/dev/null 2>&1 || true

log "starting compose services"
compose up -d --build db redis migrate api worker frontend prometheus otel-collector

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

if [[ "${AJENDA_OPERATOR_MISSION_PROOF:-0}" != "1" ]]; then
  fail "operator mission proof is required; set AJENDA_OPERATOR_MISSION_PROOF=1"
fi

log "running operator mission proof through frontend and public APIs"
AJENDA_OPERATOR_PROOF_API_BASE_URL="$API_BASE_URL" \
  AJENDA_OPERATOR_PROOF_FRONTEND_BASE_URL="${AJENDA_PROOF_FRONTEND_BASE_URL:-http://localhost:8080}" \
  python deploy/scripts/operator-mission-proof.py

log "checking live observability metrics"
metrics_body="$(curl_body "$API_BASE_URL/v1/observability/metrics")"
assert_body_contains "$metrics_body" "ajenda_tasks_completed"
assert_body_contains "$metrics_body" "ajenda_active_leases"
assert_body_contains "$metrics_body" "ajenda_worker_utilization"

log "checking Prometheus readiness and scrape target health"
wait_for_http_ok "$PROMETHEUS_BASE_URL/-/ready"
wait_for_prometheus_target_up "$PROMETHEUS_JOB_NAME"

log "live operator runtime proof passed"
