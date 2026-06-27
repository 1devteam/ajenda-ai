#!/usr/bin/env bash
# UI/UX smoke: exercise every product-page API path through the frontend nginx proxy.
set -euo pipefail

BASE_URL="${AJENDA_UI_BASE_URL:-http://localhost:8080}"
TENANT_ID="${AJENDA_UI_TENANT_ID:?set AJENDA_UI_TENANT_ID}"
API_KEY="${AJENDA_UI_API_KEY:?set AJENDA_UI_API_KEY}"

auth_headers=(
  -H "X-Tenant-Id: ${TENANT_ID}"
  -H "X-Api-Key: ${API_KEY}"
  -H "Content-Type: application/json"
)

pass=0
fail=0

check() {
  local label="$1"
  local expect="$2"
  local method="$3"
  local path="$4"
  local body="${5:-}"
  local extra=()
  if [[ -n "$body" ]]; then
    extra=(-d "$body")
  fi
  local code
  code=$(curl -s -o /tmp/ui-ux-body.json -w "%{http_code}" -X "$method" "${auth_headers[@]}" "${extra[@]}" "${BASE_URL}${path}")
  if [[ "$code" == "$expect" ]]; then
    printf 'PASS %s (%s %s -> %s)\n' "$label" "$method" "$path" "$code"
    pass=$((pass + 1))
  else
    printf 'FAIL %s (%s %s -> %s, expected %s)\n' "$label" "$method" "$path" "$code" "$expect"
    head -c 400 /tmp/ui-ux-body.json >&2 || true
    echo >&2
    fail=$((fail + 1))
  fi
}

printf '=== UI/UX smoke via %s tenant=%s ===\n' "$BASE_URL" "$TENANT_ID"

check "dashboard me" 200 GET /v1/account/me
check "dashboard plan" 200 GET /v1/account/plan
check "dashboard usage" 200 GET /v1/account/usage
check "billing status" 200 GET /v1/account/billing
check "credentials list" 200 GET /v1/account/provider-credentials
check "missions list" 200 GET "/v1/missions?limit=20"
check "autonomy disclaimers" 200 GET /v1/ability-runtime/disclaimers
check "ability actions" 200 GET /v1/ability-runtime/actions

MISSION_BODY='{"objective":"Find three qualified roofing leads in Austin and draft greeting emails for each prospect.","success_criteria":[{"description":"Three leads are documented with company name, contact email, and qualification notes ready for outreach.","evidence":["lead research summary","draft email artifacts"]}],"scope_limits":["Austin metro roofing segment"],"allowed_actions":["web.search","gtm.lead_enrich","gtm.email_draft"],"compliance_category":"operational","jurisdiction":"US-ALL"}'
check "mission create" 201 POST /v1/missions "$MISSION_BODY"

if [[ -f /tmp/ui-ux-body.json ]]; then
  MISSION_ID=$(python3 -c "import json; print(json.load(open('/tmp/ui-ux-body.json'))['mission_id'])" 2>/dev/null || true)
fi

BAD_MISSION='{"objective":"do something vague","success_criteria":[{"description":"be successful","evidence":[]}],"compliance_category":"operational","jurisdiction":"US-ALL"}'
check "mission quality deny" 422 POST /v1/missions "$BAD_MISSION"

if [[ -n "${MISSION_ID:-}" ]]; then
  check "mission read" 200 GET "/v1/missions/${MISSION_ID}"
  LAUNCH_BODY=$(printf '{"action":"web.search","input":{"query":"roofing contractors Austin","limit":3},"mission_id":"%s"}' "$MISSION_ID")
  check "mission scoped launch" 202 POST /v1/ability-runtime/tasks "$LAUNCH_BODY"
  LAUNCH_TASK_ID=$(python3 -c "import json; print(json.load(open('/tmp/ui-ux-body.json'))['task_id'])" 2>/dev/null || true)
  DISALLOWED=$(printf '{"action":"crm.research","input":{"lead":{"company":"Acme","domain":"acme.example"}},"mission_id":"%s"}' "$MISSION_ID")
  check "mission action deny" 422 POST /v1/ability-runtime/tasks "$DISALLOWED"
  if [[ -n "${LAUNCH_TASK_ID:-}" ]]; then
    check "task status poll" 200 GET "/v1/ability-runtime/tasks/${LAUNCH_TASK_ID}"
    deadline=$((SECONDS + 90))
    until [[ "$(python3 -c "import json; print(json.load(open('/tmp/ui-ux-body.json')).get('status',''))" 2>/dev/null || true)" == "completed" ]]; do
      if (( SECONDS >= deadline )); then
        printf 'FAIL task completes (GET /v1/ability-runtime/tasks/%s -> timeout)\n' "$LAUNCH_TASK_ID" >&2
        fail=$((fail + 1))
        break
      fi
      sleep 2
      curl -s -o /tmp/ui-ux-body.json -w "" -X GET "${auth_headers[@]}" "${BASE_URL}/v1/ability-runtime/tasks/${LAUNCH_TASK_ID}" >/dev/null
    done
    if [[ "$(python3 -c "import json; print(json.load(open('/tmp/ui-ux-body.json')).get('status',''))" 2>/dev/null || true)" == "completed" ]]; then
      printf 'PASS task completes (GET /v1/ability-runtime/tasks/%s -> completed)\n' "$LAUNCH_TASK_ID"
      pass=$((pass + 1))
    fi
  fi
fi

check "proof calendar-read" 202 POST /v1/ability-runtime/proofs/calendar-read "{}"

printf '=== %s passed, %s failed ===\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]