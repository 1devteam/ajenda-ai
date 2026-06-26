#!/usr/bin/env bash
# Run 12 varied live tasks (PRIDE protocol): brain + plugin lanes with fail-closed gates.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f "$HOME/.ajenda/google-cli.env" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.ajenda/google-cli.env"
fi

export PYTHONPATH="$ROOT_DIR"
export AJENDA_PROOF_API_BASE_URL="${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}"
export AJENDA_PROOF_COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
export AJENDA_PROOF_COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
export AJENDA_PROOF_TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-120}"
export AJENDA_PROOF_POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"

if [[ -z "${AJENDA_E2E_GMAIL_TOKEN:-}" ]]; then
  export AJENDA_E2E_GMAIL_TOKEN="$(python3 scripts/google/gmail_cli_auth.py token)"
fi

exec python3 "$SCRIPT_DIR/experience_lane_runner.py"