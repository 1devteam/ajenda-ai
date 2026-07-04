#!/usr/bin/env bash
# Send a live gtm.email_send proof to every address in ~/.ajenda/test-emails.env
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_EMAILS_FILE="${AJENDA_TEST_EMAILS_FILE:-$HOME/.ajenda/test-emails.env}"
API_BASE_URL="${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}"
COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-$ROOT_DIR/deploy/compose/docker-compose.prod.yml}"
COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.prod}"
TENANT_ID="${AJENDA_PROOF_TENANT_ID:-a25c9d83-9096-478a-b178-aeccf3ba7be1}"
TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-120}"
POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"

log() {
  printf '[email-send-proof] %s\n' "$*"
}

fail() {
  printf '[email-send-proof] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$TEST_EMAILS_FILE" ]] || fail "missing $TEST_EMAILS_FILE — cp scripts/dev/test-emails.env.example ~/.ajenda/test-emails.env"

set -a
# shellcheck source=/dev/null
source "$TEST_EMAILS_FILE"
set +a

RECIPIENTS=()
for var in AJENDA_TEST_EMAIL_1 AJENDA_TEST_EMAIL_2 AJENDA_TEST_EMAIL_3; do
  value="${!var:-}"
  if [[ -n "$value" ]]; then
    RECIPIENTS+=("$value")
  fi
done

if [[ ${#RECIPIENTS[@]} -eq 0 && -n "${AJENDA_TEST_EMAIL_PRIMARY:-}" ]]; then
  RECIPIENTS+=("$AJENDA_TEST_EMAIL_PRIMARY")
fi

[[ ${#RECIPIENTS[@]} -gt 0 ]] || fail "no test emails configured in $TEST_EMAILS_FILE"

log "recipients: ${RECIPIENTS[*]}"
log "tenant: $TENANT_ID"

if [[ -f "$HOME/.ajenda/google-cli.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$HOME/.ajenda/google-cli.env"
  set +a
fi

log "refreshing Gmail token..."
PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/generate_e2e_tokens.py" >/dev/null 2>&1 || true
PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/google/gmail_cli_auth.py" token >/dev/null 2>&1 || true

log "creating proof API key (tenant_admin)..."
read -r API_KEY_ID API_KEY_SECRET < <(
  docker compose -p compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" exec -T api python - <<PY
import uuid
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.services.api_key_service import ApiKeyService

tenant_id = "${TENANT_ID}"
runtime = DatabaseRuntime(get_settings())
with runtime.session_context() as session:
    plaintext, record = ApiKeyService(session=session).create_key(
        tenant_id=tenant_id,
        scopes=("execution:view", "execution:queue"),
        roles=("tenant_admin",),
        purpose="operational",
    )
    session.commit()
    print(record.key_id, plaintext)
runtime.dispose()
PY
)
API_KEY="${API_KEY_ID}.${API_KEY_SECRET}"

log "registering Gmail credential on tenant..."
PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/scripts/ajenda/provider_oauth_bridge.py" register gmail \
  --tenant-id "$TENANT_ID" \
  --api-key "$API_KEY" \
  --base-url "$API_BASE_URL" \
  --oauth-json "$HOME/.ajenda/google-oauth.yml"

AUTH_HEADERS=(
  -H "X-Tenant-Id: ${TENANT_ID}"
  -H "X-Api-Key: ${API_KEY}"
  -H "Content-Type: application/json"
)

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
idx=0
for recipient in "${RECIPIENTS[@]}"; do
  idx=$((idx + 1))
  idem="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  log "sending ${idx}/${#RECIPIENTS[@]} -> ${recipient}"
  payload="$(STAMP="$stamp" RECIPIENT="$recipient" IDEM="$idem" python3 - <<'PY'
import json
import os

stamp = os.environ["STAMP"]
recipient = os.environ["RECIPIENT"]
idem = os.environ["IDEM"]
print(
    json.dumps(
        {
            "action": "gtm.email_send",
            "input": {
                "to": recipient,
                "subject": f"Ajenda local email proof {stamp}",
                "body": f"This is a live Gmail send proof from Ajenda local dev ({stamp}).",
            },
            "idempotency_key": idem,
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
        }
    )
)
PY
)"
  response="$(curl -sf -X POST "${API_BASE_URL}/v1/ability-runtime/tasks" \
    "${AUTH_HEADERS[@]}" \
    -H "Idempotency-Key: ${idem}" \
    -d "$payload")"
  task_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["task_id"])')"

  deadline=$((SECONDS + TIMEOUT_SECONDS))
  final=""
  while (( SECONDS < deadline )); do
    status_json="$(curl -sf "${API_BASE_URL}/v1/ability-runtime/tasks/${task_id}" "${AUTH_HEADERS[@]}")"
    final="$(printf '%s' "$status_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
    if [[ "$final" == "completed" || "$final" == "failed" || "$final" == "dead_lettered" ]]; then
      break
    fi
    sleep "$POLL_SECONDS"
  done

  if [[ "$final" != "completed" ]]; then
    fail "task ${task_id} for ${recipient} ended with status=${final:-timeout}"
  fi

  send_ok="$(printf '%s' "$status_json" | python3 -c "
import json, sys
body = json.load(sys.stdin)
meta = body.get('metadata_json') or {}
handler = meta.get('handler_result') or {}
output = handler.get('output') or meta.get('output') or {}
if not output.get('real') or output.get('status') != 'sent':
    print('FAIL')
    print(output.get('error') or output.get('reason') or 'send not real')
else:
    print('OK')
    print(output.get('provider'))
")"
  if [[ "$(printf '%s' "$send_ok" | head -1)" != "OK" ]]; then
    fail "send to ${recipient} did not succeed: $(printf '%s' "$send_ok" | tail -1)"
  fi
  log "  sent via $(printf '%s' "$send_ok" | tail -1)"
done

log "done — check inboxes: ${RECIPIENTS[*]}"