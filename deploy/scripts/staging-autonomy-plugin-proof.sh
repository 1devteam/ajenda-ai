#!/usr/bin/env bash
# Staging pilot: product credentials path + optional informed autonomy tier-3 queue proof.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export AJENDA_PROOF_PLUGIN_LANE_ENABLED="${AJENDA_PROOF_PLUGIN_LANE_ENABLED:-1}"
export AJENDA_PROOF_AUTONOMY_LANE="${AJENDA_PROOF_AUTONOMY_LANE:-1}"
export AJENDA_PROOF_API_BASE_URL="${AJENDA_STAGING_API_BASE_URL:-${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}}"
export AJENDA_PROOF_COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
export AJENDA_PROOF_COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"

printf '[staging-autonomy-plugin-proof] API=%s autonomy_lane=%s\n' \
  "$AJENDA_PROOF_API_BASE_URL" "$AJENDA_PROOF_AUTONOMY_LANE"

if [[ "${AJENDA_STAGING_WAIT_FRONTEND:-0}" == "1" ]]; then
  FRONTEND_BASE_URL="${AJENDA_STAGING_FRONTEND_BASE_URL:-http://localhost:8080}"
  printf '[staging-autonomy-plugin-proof] waiting for frontend %s\n' "$FRONTEND_BASE_URL"
  deadline=$((SECONDS + ${AJENDA_PROOF_TIMEOUT_SECONDS:-120}))
  until curl --fail --silent --show-error "${FRONTEND_BASE_URL}/" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      printf '[staging-autonomy-plugin-proof] ERROR: frontend not ready\n' >&2
      exit 1
    fi
    sleep "${AJENDA_PROOF_POLL_SECONDS:-2}"
  done
fi

exec bash "$SCRIPT_DIR/plugin-runtime-proof.sh"