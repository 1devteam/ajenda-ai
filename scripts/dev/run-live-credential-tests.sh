#!/usr/bin/env bash
# Run the four opt-in live credential/plugin integration tests (Gmail, Calendar, HubSpot).
# Sources ~/.ajenda/google-cli.env and ~/.ajenda/e2e.env, refreshes tokens, checks HubSpot
# ingress health, then invokes pytest.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

AJENDA_DIR="${AJENDA_DIR:-$HOME/.ajenda}"
GOOGLE_CLI_ENV="${AJENDA_GOOGLE_CLI_ENV:-$AJENDA_DIR/google-cli.env}"
E2E_ENV="${AJENDA_E2E_ENV:-$AJENDA_DIR/e2e.env}"
ADAPTER_HOST="${AJENDA_E2E_ADAPTER_HOST:-127.0.0.1:8443}"
SKIP_REFRESH=0
PYTEST_ARGS=()

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options] [-- pytest-args...]

Runs the four live credential tests:
  - Gmail Credentials API → live inbox read
  - Google Calendar Credentials API → live events read
  - HubSpot Credentials API → live CRM search via ingress
  - HubSpot brain E2E → live adapter search + upsert

Options:
  --skip-refresh       Do not run scripts/generate_e2e_tokens.py first
  --adapter-host HOST  HubSpot TLS ingress (default: 127.0.0.1:8443)
  -h, --help           Show this help

Prerequisites:
  ~/.ajenda/google-cli.env     AJENDA_GOOGLE_CLI_CLIENT_ID/SECRET (OAuth refresh)
  ~/.ajenda/e2e.env            refreshed by: python scripts/generate_e2e_tokens.py
  ~/.hscli/config.yml or       HubSpot token via: hs account auth
    AJENDA_E2E_HUBSPOT_PAK
  HubSpot ingress healthy at   POSTGRES_PASSWORD=dev docker compose -f docker-compose.yml \\
    https://\$AJENDA_E2E_ADAPTER_HOST/health   up -d hubspot-crm-adapter hubspot-crm-ingress

Related:
  bash scripts/dev/credentials-setup-guide.sh
  python scripts/google/gmail_cli_auth.py auth
  python scripts/google/gmail_cli_auth.py calendar-auth
USAGE
}

log() {
  printf '[live-credential-tests] %s\n' "$*"
}

fail() {
  printf '[live-credential-tests] ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-refresh)
      SKIP_REFRESH=1
      shift
      ;;
    --adapter-host)
      [[ $# -ge 2 ]] || fail "--adapter-host requires a value"
      ADAPTER_HOST="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      PYTEST_ARGS=("$@")
      break
      ;;
    *)
      PYTEST_ARGS+=("$1")
      shift
      ;;
  esac
done

export PYTHONPATH="$ROOT_DIR"
export AJENDA_E2E_ADAPTER_HOST="$ADAPTER_HOST"

if [[ -f "$GOOGLE_CLI_ENV" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$GOOGLE_CLI_ENV"
  set +a
  log "loaded $GOOGLE_CLI_ENV"
else
  log "warning: missing $GOOGLE_CLI_ENV (Gmail/Calendar OAuth refresh may fail)"
fi

if [[ "$SKIP_REFRESH" -eq 0 ]]; then
  log "refreshing live E2E tokens..."
  if ! PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/generate_e2e_tokens.py"; then
    log "warning: token refresh reported missing providers; continuing with existing files"
  fi
fi

if [[ -f "$E2E_ENV" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$E2E_ENV"
  set +a
  log "loaded $E2E_ENV"
else
  fail "missing $E2E_ENV — run: python scripts/generate_e2e_tokens.py"
fi

health_url="https://${ADAPTER_HOST}/health"
log "checking HubSpot ingress: $health_url"
if ! curl -sk --max-time 8 "$health_url" | grep -q '"status"[[:space:]]*:[[:space:]]*"healthy"'; then
  fail "HubSpot ingress not healthy at $ADAPTER_HOST — run:
  bash deploy/compose/hubspot-crm-ingress/generate-certs.sh
  POSTGRES_PASSWORD=dev docker compose -f docker-compose.yml up -d hubspot-crm-adapter hubspot-crm-ingress
  curl -sk https://${ADAPTER_HOST}/health"
fi
log "HubSpot ingress healthy"

LIVE_TESTS=(
  tests/integration/credentials/test_gmail_credential_api_invoke_live_real.py::test_gmail_api_register_then_live_email_check_no_egress_mock
  tests/integration/credentials/test_google_calendar_credential_api_invoke_live_real.py::test_google_calendar_api_register_then_live_events_read_no_egress_mock
  tests/integration/credentials/test_hubspot_credential_api_invoke_live_real.py::test_hubspot_api_register_then_live_crm_research_no_egress_mock
  tests/integration/standalone/test_brain_e2e_no_simulation_real.py::test_hubspot_plugin_live_adapter_and_api_no_simulation
)

if [[ ${#PYTEST_ARGS[@]} -eq 0 ]]; then
  PYTEST_ARGS=(-v)
fi

log "running ${#LIVE_TESTS[@]} live credential tests..."
exec python -m pytest "${LIVE_TESTS[@]}" "${PYTEST_ARGS[@]}"