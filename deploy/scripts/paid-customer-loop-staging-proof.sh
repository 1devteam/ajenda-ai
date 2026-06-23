#!/usr/bin/env bash
set -euo pipefail

FRONTEND_BASE_URL="${AJENDA_STAGING_FRONTEND_BASE_URL:-http://localhost:8080}"
API_BASE_URL="${AJENDA_STAGING_API_BASE_URL:-http://localhost:8000}"
TIMEOUT_SECONDS="${AJENDA_STAGING_PROOF_TIMEOUT_SECONDS:-90}"
POLL_SECONDS="${AJENDA_STAGING_PROOF_POLL_SECONDS:-2}"
CURL_CONNECT_TIMEOUT_SECONDS="${AJENDA_STAGING_CURL_CONNECT_TIMEOUT_SECONDS:-5}"
CURL_MAX_TIME_SECONDS="${AJENDA_STAGING_CURL_MAX_TIME_SECONDS:-30}"

log() {
  printf '[paid-customer-loop-staging-proof] %s\n' "$*"
}

fail() {
  printf '[paid-customer-loop-staging-proof] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
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

require_command curl
require_command python3

log "waiting for API readiness at $API_BASE_URL/readiness"
wait_for_http_ok "$API_BASE_URL/readiness"

log "waiting for frontend readiness proxy at $FRONTEND_BASE_URL/readiness"
wait_for_http_ok "$FRONTEND_BASE_URL/readiness"

log "checking customer UI serves the SPA"
frontend_body="$(curl \
  --fail \
  --silent \
  --show-error \
  --connect-timeout "$CURL_CONNECT_TIMEOUT_SECONDS" \
  --max-time "$CURL_MAX_TIME_SECONDS" \
  "$FRONTEND_BASE_URL/")"
if ! grep -q 'id="root"' <<<"$frontend_body"; then
  fail "frontend root page missing expected SPA mount point"
fi

log "running signup → verify → promote → account reads over frontend /v1 proxy"
export FRONTEND_BASE_URL
export CURL_CONNECT_TIMEOUT_SECONDS
export CURL_MAX_TIME_SECONDS

python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

FRONTEND_BASE = os.environ["FRONTEND_BASE_URL"].rstrip("/")
CONNECT_TIMEOUT = float(os.environ["CURL_CONNECT_TIMEOUT_SECONDS"])
MAX_TIME = float(os.environ["CURL_MAX_TIME_SECONDS"])


def request(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    expected_status: int | tuple[int, ...] = 200,
) -> dict:
    payload = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    request_obj = urllib.request.Request(
        f"{FRONTEND_BASE}{path}",
        data=payload,
        headers=req_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=CONNECT_TIMEOUT + MAX_TIME) as response:
            status = response.status
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
        allowed = expected_status if isinstance(expected_status, tuple) else (expected_status,)
        if status not in allowed:
            raise RuntimeError(f"{method} {path} returned {status}: {raw}") from exc
        return json.loads(raw) if raw else {}

    allowed = expected_status if isinstance(expected_status, tuple) else (expected_status,)
    if status not in allowed:
        raise RuntimeError(f"{method} {path} returned {status}: {raw}")
    return json.loads(raw) if raw else {}


def auth_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {
        "X-Tenant-Id": tenant_id,
        "X-Api-Key": api_key,
    }


email = f"staging-proof-{uuid.uuid4().hex[:10]}@example.com"
idem = {"Idempotency-Key": str(uuid.uuid4())}

signup = request(
    "POST",
    "/v1/onboarding/signup",
    body={"org_name": "Staging Proof Co", "email": email},
    headers=idem,
    expected_status=201,
)
tenant_id = signup["tenant_id"]
token = signup.get("verification_token")
if not token:
    raise RuntimeError("signup did not expose verification_token; set AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=true for staging proof")

verify = request(
    "POST",
    "/v1/onboarding/verify-email",
    body={"token": token},
    headers={"Idempotency-Key": str(uuid.uuid4())},
    expected_status=200,
)
bootstrap_key = verify["api_key"]

request(
    "GET",
    "/v1/account/billing",
    headers=auth_headers(tenant_id, bootstrap_key),
    expected_status=403,
)

promote = request(
    "POST",
    "/v1/onboarding/promote-bootstrap-key",
    headers={
        **auth_headers(tenant_id, bootstrap_key),
        "Idempotency-Key": str(uuid.uuid4()),
    },
    expected_status=200,
)
operational_key = promote["api_key"]
auth = auth_headers(tenant_id, operational_key)

me = request("GET", "/v1/account/me", headers=auth, expected_status=200)
if me["tenant"]["plan"] != "free":
    raise RuntimeError(f"expected free plan after signup, got {me['tenant']['plan']!r}")
if me["membership"]["email"] != email:
    raise RuntimeError("account/me email mismatch")

usage = request("GET", "/v1/account/usage", headers=auth, expected_status=200)
if "missions_created" not in usage.get("usage", {}):
    raise RuntimeError("account/usage missing missions_created")

billing = request("GET", "/v1/account/billing", headers=auth, expected_status=200)
if billing.get("has_billing_account") is not False:
    raise RuntimeError("expected has_billing_account=false before Stripe checkout")

print(
    json.dumps(
        {
            "tenant_id": tenant_id,
            "email": email,
            "plan": me["tenant"]["plan"],
        },
        sort_keys=True,
    )
)
PY

log "PASS: paid customer loop staging proof complete"