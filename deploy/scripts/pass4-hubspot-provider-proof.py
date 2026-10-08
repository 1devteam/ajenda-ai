#!/usr/bin/env python3
"""Public-boundary worker proof for the Pass 4 HubSpot provider lane.

This proof registers the provider credential through Ajenda, composes and
launches a customer mission, exercises the machine/human approval boundary,
and inspects provider effect verification and tenant-scoped runtime state.
It never inserts credential/task rows or invokes a handler directly.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

BASE = os.environ.get("AJENDA_PASS4_PROOF_API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.environ.get("AJENDA_PASS4_PROOF_TIMEOUT_SECONDS", "300"))
ADAPTER_HOST = os.environ.get("AJENDA_E2E_ADAPTER_HOST", "127.0.0.1:8443")


def resolve_token() -> str:
    explicit = (
        os.environ.get("AJENDA_E2E_HUBSPOT_PAK", "").strip()
        or os.environ.get("HUBSPOT_PRIVATE_APP_TOKEN", "").strip()
        or os.environ.get("HUBSPOT_TOKEN", "").strip()
    )
    if explicit:
        return explicit
    config_path = Path.home() / ".hscli" / "config.yml"
    if not config_path.is_file():
        return ""
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""
    for account in config.get("accounts", []) if isinstance(config, dict) else []:
        if not isinstance(account, dict):
            continue
        auth = account.get("auth")
        token_info = auth.get("tokenInfo") if isinstance(auth, dict) else None
        token = token_info.get("accessToken") if isinstance(token_info, dict) else None
        if isinstance(token, str) and token.strip():
            return token.strip()
        key = account.get("personalAccessKey")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return ""


TOKEN = resolve_token()
INSTRUCTION = (
    "Research one company named HubSpot from HubSpot CRM records, qualify it, enrich its contacts, save the "
    "qualified contact to HubSpot CRM, and verify the saved record by reading it back. Do not send messages."
)


class ProofFailure(RuntimeError):
    pass


def request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected: int | tuple[int, ...] = 200,
) -> dict[str, Any]:
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_obj = urllib.request.Request(BASE + path, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            status, raw = response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode()
    allowed = (expected,) if isinstance(expected, int) else expected
    if status not in allowed:
        raise ProofFailure(f"{method} {path} returned {status}: {raw}")
    return json.loads(raw) if raw else {}


def status_request(
    method: str, path: str, *, body: dict[str, Any] | None = None, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **headers}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_obj = urllib.request.Request(BASE + path, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def require(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProofFailure(f"missing {key}")
    return value


def machine_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def verified_provider_record_ids(payload: Any) -> set[str]:
    """Collect only positively verified provider record IDs from runtime evidence."""

    found: set[str] = set()
    if isinstance(payload, dict):
        record_id = payload.get("provider_record_id")
        if payload.get("verified") is True and isinstance(record_id, str) and record_id:
            found.add(record_id)
        for value in payload.values():
            found.update(verified_provider_record_ids(value))
    elif isinstance(payload, list):
        for value in payload:
            found.update(verified_provider_record_ids(value))
    return found


def create_tenant() -> tuple[str, str, str, str]:
    email = f"pass4-proof-{uuid.uuid4().hex[:10]}@example.com"
    password = "Pass4-proof-password-2026!"
    ip = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    signup = request(
        "POST",
        "/v1/onboarding/signup",
        body={"org_name": "Ajenda Pass 4 HubSpot Proof", "email": email, "password": password},
        headers={"X-Forwarded-For": ip, "Idempotency-Key": str(uuid.uuid4())},
        expected=(201, 202),
    )
    verification = request(
        "POST",
        "/v1/onboarding/verify-email",
        body={"email": email, "code": require(signup, "verification_code")},
        headers={"X-Forwarded-For": ip, "Idempotency-Key": str(uuid.uuid4())},
    )
    tenant_id = require(verification, "tenant_id")
    bootstrap = require(verification, "api_key")
    promoted = request(
        "POST",
        "/v1/onboarding/promote-bootstrap-key",
        headers={**machine_headers(tenant_id, bootstrap), "Idempotency-Key": str(uuid.uuid4())},
    )
    return tenant_id, require(promoted, "api_key"), email, password


def register_hubspot(tenant_id: str, machine_key: str) -> dict[str, Any]:
    if not TOKEN:
        raise ProofFailure("No operator-controlled HubSpot credential source was available")
    return request(
        "POST",
        "/v1/account/provider-credentials",
        body={
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "integration": "hubspot",
            "secret_value": TOKEN,
            "allowed_actions": ["crm.research", "sales.research", "gtm.crm_upsert"],
            "allowed_side_effect_classes": ["external_read", "external_write"],
            "trusted_destination_hosts": [ADAPTER_HOST],
        },
        headers={**machine_headers(tenant_id, machine_key), "Idempotency-Key": str(uuid.uuid4())},
        expected=201,
    )


def main() -> int:
    tenant_id, machine_key, email, password = create_tenant()
    machine = machine_headers(tenant_id, machine_key)
    credential_response = register_hubspot(tenant_id, machine_key)
    credential = credential_response.get("credential", {})
    credential_id = require(credential, "credential_id")
    serialized_credential = json.dumps(credential_response, sort_keys=True)
    if TOKEN in serialized_credential:
        raise ProofFailure("credential registration response exposed plaintext secret")

    proposal = request("POST", "/v1/missions/compose", body={"instruction": INSTRUCTION}, headers=machine)
    if proposal.get("ready_to_start") is not True:
        raise ProofFailure(f"HubSpot composition was not ready: {proposal}")
    plan = proposal.get("planned_steps") or []
    actions = {
        step.get("action_name") or step.get("metadata", {}).get("action") for step in plan if isinstance(step, dict)
    }
    if "web.research" in actions or "web.search" in actions:
        raise ProofFailure(f"HubSpot mission selected public discovery: {actions}")
    if not ({"sales.research", "crm.research"} & actions):
        raise ProofFailure(f"composition omitted HubSpot research action: {actions}")
    if "gtm.crm_upsert" not in actions:
        raise ProofFailure(f"composition omitted governed HubSpot write: {actions}")
    if credential_id not in json.dumps(proposal, sort_keys=True):
        raise ProofFailure("composition did not retain the tenant credential reference")
    if TOKEN in json.dumps(proposal, sort_keys=True):
        raise ProofFailure("composition exposed plaintext HubSpot secret")

    confirmed = request(
        "POST",
        f"/v1/missions/proposals/{require(proposal, 'proposal_id')}/confirm",
        body={"idempotency_key": str(uuid.uuid4())},
        headers=machine,
    )
    mission_id = require(confirmed, "mission_id")
    launch_idempotency_key = str(uuid.uuid4())
    launch = request(
        "POST",
        f"/v1/missions/{mission_id}/launch",
        headers={**machine, "Idempotency-Key": launch_idempotency_key},
    )
    pending = launch.get("pending_review_task_ids") or []
    if len(pending) != 1:
        raise ProofFailure(f"expected exactly one pending HubSpot write: {launch}")
    task_id = str(pending[0])
    launch_text = json.dumps(launch, sort_keys=True)
    if TOKEN in launch_text:
        raise ProofFailure("launch response exposed plaintext HubSpot secret")

    other_tenant, other_key, _, _ = create_tenant()
    other = machine_headers(other_tenant, other_key)
    status, _ = status_request(
        "POST",
        f"/v1/review-queue/tasks/{task_id}/approve",
        body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=other,
    )
    if status not in {403, 404}:
        raise ProofFailure(f"cross-tenant review approval was not blocked: {status}")
    status, _ = status_request("GET", f"/v1/missions/{mission_id}/runtime-evidence", headers=other)
    if status not in {403, 404}:
        raise ProofFailure(f"cross-tenant evidence access was not blocked: {status}")

    status, _ = status_request(
        "POST",
        f"/v1/review-queue/tasks/{task_id}/approve",
        body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=machine,
    )
    if status != 403:
        raise ProofFailure(f"tenant_operator self-approval was not denied: {status}")

    login = request(
        "POST",
        "/v1/auth/password",
        body={"email": email, "password": password, "tenant_id": tenant_id},
        headers={"X-Forwarded-For": f"198.51.100.{uuid.uuid4().int % 254 + 1}"},
    )
    owner = {"X-Tenant-Id": tenant_id, "Authorization": f"Bearer {require(login, 'access_token')}"}
    me = request("GET", "/v1/auth/me", headers=owner)
    if me.get("principal_type") != "user" or "outcome_review:manage" not in me.get("permissions", []):
        raise ProofFailure(f"tenant owner is not an authorized reviewer: {me}")

    deadline = time.time() + TIMEOUT
    approved = False
    while time.time() < deadline:
        status, body = status_request(
            "POST",
            f"/v1/review-queue/tasks/{task_id}/approve",
            body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
            headers=owner,
        )
        if status == 200:
            approved = True
            break
        if status != 409:
            raise ProofFailure(f"owner approval failed: {status} {body}")
        time.sleep(2)
    if not approved:
        raise ProofFailure("owner approval never became dependency-ready")

    lifecycle: dict[str, Any] = {}
    while time.time() < deadline:
        lifecycle = request("GET", f"/v1/missions/{mission_id}/lifecycle", headers=machine)
        if lifecycle.get("mission", {}).get("status") in {"completed", "failed"}:
            break
        time.sleep(2)
    evidence = request("GET", f"/v1/missions/{mission_id}/runtime-evidence", headers=machine)
    deliverable = request("GET", f"/v1/missions/{mission_id}/deliverable", headers=machine)
    combined = json.dumps({"lifecycle": lifecycle, "evidence": evidence, "deliverable": deliverable}, sort_keys=True)
    if TOKEN in combined:
        raise ProofFailure("runtime state exposed plaintext HubSpot secret")
    if lifecycle.get("mission", {}).get("status") != "completed":
        raise ProofFailure(f"HubSpot mission did not complete: {lifecycle}")
    if "effect_verified" not in combined or "readback" not in combined:
        raise ProofFailure("runtime evidence omitted provider effect verification/read-back")
    if evidence.get("first_divergence") is not None:
        raise ProofFailure(f"runtime first divergence was reported: {evidence['first_divergence']}")
    if evidence.get("contradictions"):
        raise ProofFailure(f"runtime contradictions were reported: {evidence['contradictions']}")
    if evidence.get("acceptance", {}).get("status") != "met":
        raise ProofFailure(f"HubSpot acceptance did not pass: {evidence.get('acceptance')}")
    if deliverable.get("completion", {}).get("complete") is not True:
        raise ProofFailure(f"HubSpot deliverable did not complete: {deliverable}")

    initial_provider_ids = verified_provider_record_ids(evidence)
    if len(initial_provider_ids) != 1:
        raise ProofFailure(f"expected exactly one verified HubSpot provider record: {initial_provider_ids}")

    replay_launch = request(
        "POST",
        f"/v1/missions/{mission_id}/launch",
        headers={**machine, "Idempotency-Key": launch_idempotency_key},
    )
    if int(replay_launch.get("runtime_tasks_materialized") or 0) != 0:
        raise ProofFailure(f"replay materialized duplicate runtime tasks: {replay_launch}")
    if replay_launch.get("queued_task_ids") or replay_launch.get("pending_review_task_ids"):
        raise ProofFailure(f"replay re-admitted completed provider work: {replay_launch}")

    replay_evidence = request("GET", f"/v1/missions/{mission_id}/runtime-evidence", headers=machine)
    replay_provider_ids = verified_provider_record_ids(replay_evidence)
    if replay_provider_ids != initial_provider_ids:
        raise ProofFailure(
            "governed replay changed the verified HubSpot provider identity: "
            f"before={sorted(initial_provider_ids)} after={sorted(replay_provider_ids)}"
        )

    print(
        json.dumps(
            {
                "pass4": "success",
                "tenant_id": tenant_id,
                "mission_id": mission_id,
                "task_id": task_id,
                "provider_record_id": next(iter(initial_provider_ids)),
                "governed_replay": "no_duplicate_task_or_provider_identity",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
