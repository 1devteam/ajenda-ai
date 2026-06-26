#!/usr/bin/env bash
# Env-gated plugin lane: Credentials API register → worker tool.invoke → live external egress.
# Optional autonomy tier-3 lane when AJENDA_PROOF_AUTONOMY_LANE=1 and API mode is pilot/enforce.
set -euo pipefail

API_BASE_URL="${AJENDA_PROOF_API_BASE_URL:-http://localhost:8000}"
COMPOSE_FILE="${AJENDA_PROOF_COMPOSE_FILE:-deploy/compose/docker-compose.prod.yml}"
COMPOSE_ENV_FILE="${AJENDA_PROOF_COMPOSE_ENV_FILE:-deploy/compose/.env.prod}"
TIMEOUT_SECONDS="${AJENDA_PROOF_TIMEOUT_SECONDS:-120}"
POLL_SECONDS="${AJENDA_PROOF_POLL_SECONDS:-2}"
ADAPTER_HOST="${AJENDA_E2E_ADAPTER_HOST:-127.0.0.1:8443}"
ROOT_COMPOSE_FILE="${AJENDA_PROOF_ROOT_COMPOSE_FILE:-docker-compose.yml}"

log() {
  printf '[plugin-runtime-proof] %s\n' "$*"
}

fail() {
  printf '[plugin-runtime-proof] ERROR: %s\n' "$*" >&2
  exit 1
}

skip() {
  printf '[plugin-runtime-proof] SKIP: %s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

compose() {
  docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

resolve_hubspot_token() {
  if [[ -n "${AJENDA_E2E_HUBSPOT_PAK:-}" ]]; then
    printf '%s' "$AJENDA_E2E_HUBSPOT_PAK"
    return 0
  fi
  python3 - <<'PY'
from pathlib import Path

import yaml

config_path = Path.home() / ".hscli" / "config.yml"
if not config_path.is_file():
    raise SystemExit(1)
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
accounts = config.get("accounts") if isinstance(config, dict) else None
if not isinstance(accounts, list):
    raise SystemExit(1)
for account in accounts:
    if not isinstance(account, dict):
        continue
    auth = account.get("auth")
    if isinstance(auth, dict):
        token_info = auth.get("tokenInfo")
        if isinstance(token_info, dict):
            token = token_info.get("accessToken")
            if isinstance(token, str) and token.strip():
                print(token.strip())
                raise SystemExit(0)
    pak = account.get("personalAccessKey")
    if isinstance(pak, str) and pak.strip():
        print(pak.strip())
        raise SystemExit(0)
raise SystemExit(1)
PY
}

resolve_gmail_token() {
  if [[ -n "${AJENDA_E2E_GMAIL_TOKEN:-}" ]]; then
    printf '%s' "$AJENDA_E2E_GMAIL_TOKEN"
    return 0
  fi
  python3 - <<'PY'
from pathlib import Path

import yaml

config_path = Path.home() / ".ajenda" / "google-oauth.yml"
if not config_path.is_file():
    raise SystemExit(1)
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
if not isinstance(config, dict):
    raise SystemExit(1)
token = config.get("access_token")
if isinstance(token, str) and token.strip():
    print(token.strip())
    raise SystemExit(0)
raise SystemExit(1)
PY
}

ensure_hubspot_ingress() {
  local host="${ADAPTER_HOST%%:*}"
  local port="${ADAPTER_HOST##*:}"
  if [[ "$host" == "$port" ]]; then
    port="8443"
  fi
  if python3 - <<PY
import socket
socket.create_connection(("${host}", int("${port}")), timeout=2).close()
PY
  then
    return 0
  fi
  if [[ "${AJENDA_PROOF_START_HUBSPOT_INGRESS:-1}" != "1" ]]; then
    fail "HubSpot ingress not reachable at ${ADAPTER_HOST}"
  fi
  if [[ ! -f "$ROOT_COMPOSE_FILE" ]]; then
    fail "HubSpot ingress not reachable and ${ROOT_COMPOSE_FILE} not found"
  fi
  log "starting HubSpot adapter + ingress from ${ROOT_COMPOSE_FILE}"
  docker compose -f "$ROOT_COMPOSE_FILE" up -d hubspot-crm-adapter hubspot-crm-ingress
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  until python3 - <<PY
import socket
socket.create_connection(("${host}", int("${port}")), timeout=2).close()
PY
  do
    if (( SECONDS >= deadline )); then
      fail "timed out waiting for HubSpot ingress at ${ADAPTER_HOST}"
    fi
    sleep "$POLL_SECONDS"
  done
}

run_http_and_worker_proof() {
  local lane="$1"
  local hubspot_token="${2:-}"
  local gmail_token="${3:-}"
  export API_BASE_URL
  export TIMEOUT_SECONDS
  export POLL_SECONDS
  export ADAPTER_HOST
  export LANE="$lane"
  export HUBSPOT_TOKEN="$hubspot_token"
  export GMAIL_TOKEN="$gmail_token"
  export COMPOSE_FILE
  export COMPOSE_ENV_FILE

  if [[ ! -f "$COMPOSE_FILE" || ! -f "$COMPOSE_ENV_FILE" ]]; then
    fail "compose files required for worker proof: $COMPOSE_FILE and $COMPOSE_ENV_FILE"
  fi

  python3 - <<'PY'
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API_BASE = os.environ["API_BASE_URL"].rstrip("/")
TIMEOUT_SECONDS = float(os.environ["TIMEOUT_SECONDS"])
POLL_SECONDS = float(os.environ["POLL_SECONDS"])
LANE = os.environ["LANE"]
HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
GMAIL_TOKEN = os.environ.get("GMAIL_TOKEN", "")
COMPOSE_FILE = os.environ["COMPOSE_FILE"]
COMPOSE_ENV_FILE = os.environ["COMPOSE_ENV_FILE"]
ADAPTER_HOST = os.environ.get("ADAPTER_HOST", "127.0.0.1:8443")


def request(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    expected: int | tuple[int, ...] = 200,
) -> dict:
    payload = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_BASE}{path}", data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
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


def provision_tenant() -> tuple[str, str, str]:
    email = f"plugin-proof-{uuid.uuid4().hex[:10]}@example.com"
    signup = request(
        "POST",
        "/v1/onboarding/signup",
        body={"org_name": "Plugin Proof Co", "email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
        expected=201,
    )
    tenant_id = signup["tenant_id"]
    token = signup.get("verification_token")
    if not token:
        raise RuntimeError("signup missing verification_token; enable AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN")
    verify = request(
        "POST",
        "/v1/onboarding/verify-email",
        body={"token": token},
        headers={"Idempotency-Key": str(uuid.uuid4())},
        expected=200,
    )
    bootstrap_key = verify["api_key"]
    promote = request(
        "POST",
        "/v1/onboarding/promote-bootstrap-key",
        headers={**auth_headers(tenant_id, bootstrap_key), "Idempotency-Key": str(uuid.uuid4())},
        expected=200,
    )
    return tenant_id, promote["api_key"], email


def upgrade_tenant_plan(tenant_id: str, plan: str = "pro") -> None:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        COMPOSE_ENV_FILE,
        "-f",
        COMPOSE_FILE,
        "exec",
        "-T",
        "api",
        "python",
        "-",
        tenant_id,
        plan,
    ]
    script = """
import sys
import uuid
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.tenant import Tenant

tenant_id = sys.argv[1]
plan = sys.argv[2]
runtime = DatabaseRuntime(get_settings())
session = runtime.session_factory()
try:
    tenant = session.get(Tenant, uuid.UUID(tenant_id))
    if tenant is None:
        raise RuntimeError(f"tenant not found: {tenant_id}")
    tenant.plan = plan
    session.commit()
finally:
    session.close()
runtime.dispose()
"""
    proc = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True, text=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace") or "plan upgrade failed")


def queue_tool_invoke_and_wait(
    *,
    tenant_id: str,
    action: str,
    input_payload: dict,
    credential_id: str,
    provider: str,
) -> dict:
    cmd = [
        "docker",
        "compose",
        "--env-file",
        COMPOSE_ENV_FILE,
        "-f",
        COMPOSE_FILE,
        "exec",
        "-T",
        "-e",
        f"AJENDA_PROOF_TIMEOUT_SECONDS={TIMEOUT_SECONDS}",
        "-e",
        f"AJENDA_PROOF_POLL_SECONDS={POLL_SECONDS}",
        "-e",
        f"AJENDA_PROOF_TENANT_ID={tenant_id}",
        "-e",
        f"AJENDA_PROOF_ACTION={action}",
        "-e",
        f"AJENDA_PROOF_CREDENTIAL_ID={credential_id}",
        "-e",
        f"AJENDA_PROOF_PROVIDER={provider}",
        "-e",
        f"AJENDA_PROOF_INPUT_JSON={json.dumps(input_payload)}",
        "api",
        "python",
        "-",
    ]
    worker_script = r'''
import json
import os
import time
import uuid

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.queue import build_queue_adapter
from backend.services.execution_coordinator import ExecutionCoordinator

tenant_id = os.environ["AJENDA_PROOF_TENANT_ID"]
action = os.environ["AJENDA_PROOF_ACTION"]
credential_id = os.environ["AJENDA_PROOF_CREDENTIAL_ID"]
provider = os.environ["AJENDA_PROOF_PROVIDER"]
input_payload = json.loads(os.environ["AJENDA_PROOF_INPUT_JSON"])
timeout_seconds = float(os.environ["AJENDA_PROOF_TIMEOUT_SECONDS"])
poll_seconds = float(os.environ["AJENDA_PROOF_POLL_SECONDS"])

settings = get_settings()
runtime = DatabaseRuntime(settings)
queue = build_queue_adapter(settings)
try:
    session = runtime.session_factory()
    try:
        mission = Mission(tenant_id=tenant_id, objective=f"Plugin proof {action}", status="running")
        session.add(mission)
        session.flush()
        metadata = {
            "task_type": "tool.invoke",
            "tool_invocation": {"action": action, "input": input_payload},
            "credential_reference": {
                "schema_version": 1,
                "credential_id": credential_id,
                "provider": provider,
                "credential_type": "api_key",
            },
        }
        if action == "gtm.crm_upsert":
            metadata["execution_constraints"] = {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": [action],
                    "reason": "plugin-runtime-proof",
                    "approved_by": "plugin-runtime-proof",
                }
            }
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=f"Plugin proof {action}",
            description="plugin-runtime-proof worker lane",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json=metadata,
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        queued = ExecutionCoordinator(session, queue).queue_task(tenant_id=tenant_id, task_id=task_id)
        if not queued.ok:
            raise RuntimeError(queued.reason or "queue rejected")
        session.commit()
    finally:
        session.close()

    deadline = time.monotonic() + timeout_seconds
    final_status = None
    output = None
    while time.monotonic() < deadline:
        session = runtime.session_factory()
        try:
            current = session.get(ExecutionTask, task_id)
            if current is None:
                raise RuntimeError("task disappeared")
            if current.status in {
                ExecutionTaskState.COMPLETED.value,
                ExecutionTaskState.FAILED.value,
                ExecutionTaskState.DEAD_LETTERED.value,
            }:
                final_status = current.status
                output = current.metadata_json.get("output")
                break
        finally:
            session.close()
        time.sleep(poll_seconds)

    if final_status != ExecutionTaskState.COMPLETED.value:
        raise RuntimeError(f"task {task_id} final_status={final_status!r}")
    print(json.dumps({"task_id": str(task_id), "status": final_status, "output": output}, sort_keys=True))
finally:
    runtime.dispose()
'''
    proc = subprocess.run(cmd, input=worker_script.encode("utf-8"), capture_output=True, text=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace") or proc.stdout.decode("utf-8", errors="replace"))
    line = proc.stdout.decode("utf-8").strip().splitlines()[-1]
    return json.loads(line)


def assert_not_simulated(output: object) -> None:
    blob = json.dumps(output).lower()
    if "simulated" in blob:
        raise RuntimeError(f"simulated output forbidden: {output!r}")
    if isinstance(output, dict) and output.get("status") == "simulated":
        raise RuntimeError(f"simulated status forbidden: {output!r}")


def run_hubspot_lane() -> dict:
    if not HUBSPOT_TOKEN:
        raise RuntimeError("missing HubSpot token")
    host, _, port = ADAPTER_HOST.partition(":")
    socket.create_connection((host, int(port or "8443")), timeout=2).close()

    tenant_id, api_key, _email = provision_tenant()
    auth = auth_headers(tenant_id, api_key)
    create = request(
        "POST",
        "/v1/account/provider-credentials",
        headers=auth,
        body={
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "integration": "hubspot",
            "secret_value": HUBSPOT_TOKEN,
        },
        expected=201,
    )
    if create["credential"]["credential_id"] != "hubspot-crm":
        raise RuntimeError("unexpected credential response")
    result = queue_tool_invoke_and_wait(
        tenant_id=tenant_id,
        action="crm.research",
        input_payload={"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
        credential_id="hubspot-crm",
        provider="external_crm",
    )
    assert_not_simulated(result.get("output"))
    return {"lane": "hubspot", "tenant_id": tenant_id, **result}


def run_gmail_lane() -> dict:
    if not GMAIL_TOKEN:
        raise RuntimeError("missing Gmail token")
    tenant_id, api_key, _email = provision_tenant()
    auth = auth_headers(tenant_id, api_key)
    request(
        "POST",
        "/v1/account/provider-credentials",
        headers=auth,
        body={
            "credential_id": "gmail-email",
            "provider": "external_email",
            "integration": "gmail",
            "secret_value": GMAIL_TOKEN,
        },
        expected=201,
    )
    result = queue_tool_invoke_and_wait(
        tenant_id=tenant_id,
        action="gtm.email_check",
        input_payload={"query": "in:inbox", "limit": 3},
        credential_id="gmail-email",
        provider="external_email",
    )
    output = result.get("output")
    assert_not_simulated(output)
    if isinstance(output, dict) and output.get("emails"):
        first_id = output["emails"][0].get("id")
        if first_id == "sim-1":
            raise RuntimeError("gmail check returned simulated message id")
    return {"lane": "gmail", "tenant_id": tenant_id, **result}


def run_autonomy_lane() -> dict:
    tenant_id, api_key, _email = provision_tenant()
    auth = auth_headers(tenant_id, api_key)
    disclaimers = request("GET", "/v1/ability-runtime/disclaimers", headers=auth, expected=200)
    mode = disclaimers.get("mode", "off")
    if mode not in {"pilot", "enforce"}:
        raise RuntimeError(
            f"autonomy lane requires AJENDA_AUTONOMY_DISCLAIMER_MODE=pilot|enforce on API; got {mode!r}"
        )
    upgrade_tenant_plan(tenant_id, "pro")
    me = request("GET", "/v1/account/me", headers=auth, expected=200)
    principal_id = me["principal"]["subject_id"]
    if not HUBSPOT_TOKEN:
        raise RuntimeError("autonomy tier-3 lane requires HubSpot token for gtm.crm_upsert")
    request(
        "POST",
        "/v1/account/provider-credentials",
        headers=auth,
        body={
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "integration": "hubspot",
            "secret_value": HUBSPOT_TOKEN,
        },
        expected=201,
    )
    disclaimer = next(
        (item for item in disclaimers.get("disclaimers", []) if "gtm.crm_upsert" in item.get("actions", [])),
        None,
    )
    if disclaimer is None:
        raise RuntimeError("disclaimer catalog missing gtm.crm_upsert entry")
    launch = request(
        "POST",
        "/v1/ability-runtime/tasks",
        headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
        body={
            "action": "gtm.crm_upsert",
            "input": {
                "record_type": "contact",
                "data": {"email": "plugin-proof@example.com", "firstname": "Plugin"},
            },
            "idempotency_key": f"plugin-proof-{uuid.uuid4().hex[:8]}",
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            "autonomy_acknowledgment": {
                "schema_version": 1,
                "disclaimer_id": disclaimer["disclaimer_id"],
                "disclaimer_text_hash": disclaimer["text_hash"],
                "accepted_at": "2026-06-26T12:00:00+00:00",
                "principal_id": principal_id,
                "action": "gtm.crm_upsert",
                "side_effect_class": "external_write",
            },
        },
        expected=202,
    )
    task_id = launch["task_id"]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    final = None
    audit_actions: list[str] = []
    while time.monotonic() < deadline:
        status = request("GET", f"/v1/ability-runtime/tasks/{task_id}", headers=auth, expected=200)
        final = status.get("status")
        audit_actions = [item.get("action") for item in status.get("audit", []) if isinstance(item, dict)]
        if final in {"completed", "failed", "dead_lettered"}:
            break
        time.sleep(POLL_SECONDS)
    if final != "completed":
        raise RuntimeError(f"autonomy task {task_id} final_status={final!r}")
    if "autonomy_disclaimer_accepted" not in audit_actions:
        raise RuntimeError(f"missing autonomy_disclaimer_accepted audit; got {audit_actions!r}")
    return {
        "lane": "autonomy_tier3",
        "tenant_id": tenant_id,
        "task_id": task_id,
        "principal_id": principal_id,
        "status": final,
        "audit_actions": audit_actions,
    }


results: list[dict] = []
if LANE == "hubspot":
    results.append(run_hubspot_lane())
elif LANE == "gmail":
    results.append(run_gmail_lane())
elif LANE == "autonomy":
    results.append(run_autonomy_lane())
else:
    raise RuntimeError(f"unknown lane: {LANE}")

print(json.dumps(results[-1], sort_keys=True))
PY
}

main() {
  require_command docker
  require_command python3
  require_command curl

  if [[ "${AJENDA_PROOF_PLUGIN_LANE_ENABLED:-}" != "1" ]]; then
    skip "set AJENDA_PROOF_PLUGIN_LANE_ENABLED=1 to run plugin lane"
    exit 0
  fi

  log "waiting for API readiness at ${API_BASE_URL}/readiness"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  until curl --fail --silent --show-error "${API_BASE_URL}/readiness" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      fail "API not ready at ${API_BASE_URL}/readiness"
    fi
    sleep "$POLL_SECONDS"
  done

  local ran=0

  if hubspot_token="$(resolve_hubspot_token 2>/dev/null || true)" && [[ -n "$hubspot_token" ]]; then
    ensure_hubspot_ingress
    log "running HubSpot credential API → worker → live adapter proof"
    hubspot_json="$(run_http_and_worker_proof hubspot "$hubspot_token" "")"
    log "hubspot proof: $hubspot_json"
    ran=1
  else
    skip "HubSpot lane (set AJENDA_E2E_HUBSPOT_PAK or hs CLI auth)"
  fi

  if gmail_token="$(resolve_gmail_token 2>/dev/null || true)" && [[ -n "$gmail_token" ]]; then
    log "running Gmail credential API → worker → live API proof"
    gmail_json="$(run_http_and_worker_proof gmail "" "$gmail_token")"
    log "gmail proof: $gmail_json"
    ran=1
  else
    skip "Gmail lane (set AJENDA_E2E_GMAIL_TOKEN or ~/.ajenda/google-oauth.yml)"
  fi

  if [[ "${AJENDA_PROOF_AUTONOMY_LANE:-}" == "1" ]]; then
    if [[ -z "${hubspot_token:-}" ]]; then
      hubspot_token="$(resolve_hubspot_token 2>/dev/null || true)"
    fi
    if [[ -n "${hubspot_token:-}" ]]; then
      ensure_hubspot_ingress
      log "running informed autonomy tier-3 ability-runtime proof"
      autonomy_json="$(run_http_and_worker_proof autonomy "$hubspot_token" "")"
      log "autonomy proof: $autonomy_json"
      ran=1
    else
      skip "autonomy lane requires HubSpot token"
    fi
  fi

  if [[ "$ran" -eq 0 ]]; then
    fail "no plugin lanes executed; provide tokens or disable AJENDA_PROOF_PLUGIN_LANE_ENABLED"
  fi

  log "plugin runtime proof passed"
}

main "$@"