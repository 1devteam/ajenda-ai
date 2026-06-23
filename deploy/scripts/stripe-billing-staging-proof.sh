#!/usr/bin/env bash
# Prove signup → promote → Stripe webhook plan sync → ability launch on local staging.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${AJENDA_RUNTIME_ENV_FILE:-$ROOT_DIR/deploy/compose/.env.prod}"
FRONTEND_BASE_URL="${AJENDA_STAGING_FRONTEND_BASE_URL:-http://localhost:8080}"
API_BASE_URL="${AJENDA_STAGING_API_BASE_URL:-http://localhost:8000}"

log() {
  printf '[stripe-billing-staging-proof] %s\n' "$*"
}

fail() {
  printf '[stripe-billing-staging-proof] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$ENV_FILE" ]] || fail "missing runtime env file: $ENV_FILE"

log "phase 1/2: onboarding proof"
bash "$ROOT_DIR/deploy/scripts/paid-customer-loop-staging-proof.sh"

log "phase 2/2: stripe webhook plan sync + ability launch"
export ROOT_DIR ENV_FILE FRONTEND_BASE_URL API_BASE_URL
python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from backend.billing.staging_proof_helpers import (
    build_checkout_completed_event,
    dumps_event,
    sign_stripe_webhook_payload,
    stripe_webhook_proof_ready,
)

ROOT = Path(os.environ["ROOT_DIR"])
ENV_FILE = Path(os.environ["ENV_FILE"])
FRONTEND = os.environ["FRONTEND_BASE_URL"].rstrip("/")
API = os.environ["API_BASE_URL"].rstrip("/")
env_text = ENV_FILE.read_text(encoding="utf-8")


def env_value(key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}=(.*)$", env_text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


secret_key = env_value("STRIPE_SECRET_KEY")
webhook_secret = env_value("STRIPE_WEBHOOK_SECRET")
price_pro = env_value("STRIPE_PRICE_PRO")

if not stripe_webhook_proof_ready(webhook_secret=webhook_secret, price_pro=price_pro):
    print(
        "Stripe staging is not fully configured.\n"
        "Run: bash deploy/scripts/stripe-staging-bootstrap.sh\n"
        "Or set STRIPE_SECRET_KEY (sk_test_…), STRIPE_WEBHOOK_SECRET (whsec_…), "
        "and STRIPE_PRICE_PRO (price_…) in deploy/compose/.env.staging, sync to .env.prod, "
        "and restart api.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def request(
    base: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    expected: int | tuple[int, ...] = 200,
) -> dict:
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(f"{base}{path}", data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            status = response.status
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
        allowed = expected if isinstance(expected, tuple) else (expected,)
        if status not in allowed:
            raise RuntimeError(f"{method} {path} -> {status}: {raw}") from exc
        return json.loads(raw) if raw else {}

    allowed = expected if isinstance(expected, tuple) else (expected,)
    if status not in allowed:
        raise RuntimeError(f"{method} {path} -> {status}: {raw}")
    return json.loads(raw) if raw else {}


def auth_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


email = f"billing-proof-{uuid.uuid4().hex[:8]}@example.com"
signup = request(
    FRONTEND,
    "POST",
    "/v1/onboarding/signup",
    body=json.dumps({"org_name": "Billing Proof Co", "email": email}).encode(),
    headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
    expected=201,
)
tenant_id = signup["tenant_id"]
token = signup.get("verification_token")
if not token:
    raise RuntimeError("signup did not expose verification_token for staging proof")

verify = request(
    FRONTEND,
    "POST",
    "/v1/onboarding/verify-email",
    body=json.dumps({"token": token}).encode(),
    headers={"Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())},
)
bootstrap_key = verify["api_key"]

promote = request(
    FRONTEND,
    "POST",
    "/v1/onboarding/promote-bootstrap-key",
    headers={
        **auth_headers(tenant_id, bootstrap_key),
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    },
    body=b"{}",
)
operational_key = promote["api_key"]
auth = auth_headers(tenant_id, operational_key)

me_before = request(FRONTEND, "GET", "/v1/account/me", headers=auth)
if me_before["tenant"]["plan"] != "free":
    raise RuntimeError(f"expected free plan before webhook, got {me_before['tenant']['plan']!r}")

customer_id = f"cus_{uuid.uuid4().hex[:12]}"
event = build_checkout_completed_event(
    tenant_id=tenant_id,
    customer_id=customer_id,
    price_id=price_pro,
)
payload = dumps_event(event)
signature = sign_stripe_webhook_payload(payload, secret=webhook_secret)

webhook = request(
    API,
    "POST",
    "/v1/billing/webhook/stripe",
    body=payload,
    headers={"Content-Type": "application/json", "stripe-signature": signature},
)
if webhook.get("outcome") not in {"applied", "skipped"}:
    raise RuntimeError(f"unexpected webhook outcome: {webhook!r}")

me_after = request(FRONTEND, "GET", "/v1/account/me", headers=auth)
if me_after["tenant"]["plan"] != "pro":
    raise RuntimeError(f"expected pro plan after webhook, got {me_after['tenant']['plan']!r}")

proof = request(
    FRONTEND,
    "POST",
    "/v1/ability-runtime/proofs/calendar-read",
    headers=auth,
    expected=202,
)
if not proof.get("task_id"):
    raise RuntimeError(f"ability proof did not return task_id: {proof!r}")

print(
    json.dumps(
        {
            "tenant_id": tenant_id,
            "email": email,
            "plan_before": "free",
            "plan_after": me_after["tenant"]["plan"],
            "webhook_outcome": webhook.get("outcome"),
            "task_id": proof["task_id"],
            "action": proof.get("action"),
        },
        sort_keys=True,
    )
)
PY

log "PASS: stripe billing staging proof complete"