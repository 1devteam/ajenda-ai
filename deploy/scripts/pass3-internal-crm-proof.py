#!/usr/bin/env python3
"""Public-boundary worker proof for the Pass 3 internal CRM value chain.

The proof creates its tenants and CRM fixtures through API routes, keeps the
machine and human identities separate, and never writes runtime state directly.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

BASE = os.environ.get("AJENDA_PASS3_PROOF_API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.environ.get("AJENDA_PASS3_PROOF_TIMEOUT_SECONDS", "240"))
INSTRUCTION = (
    "Review the three HVAC companies already saved in Ajenda internal CRM, qualify them, enrich the contacts, "
    "persist the qualified prospects to Ajenda internal CRM, read back every saved record, and return a "
    "customer-readable list containing company name, website, qualification score, and qualification evidence. "
    "Do not send messages."
)


class ProofFailure(RuntimeError):
    """Raised when a Pass 3 invariant is not proven."""


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


def require(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProofFailure(f"missing {key}")
    return value


def machine_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def create_tenant() -> tuple[str, str, str, str]:
    email = f"pass3-proof-{uuid.uuid4().hex[:10]}@example.com"
    password = "Pass3-proof-password-2026!"
    client_ip = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    signup = request(
        "POST",
        "/v1/onboarding/signup",
        body={"org_name": "Ajenda Pass 3 Proof", "email": email, "password": password},
        headers={"X-Forwarded-For": client_ip, "Idempotency-Key": str(uuid.uuid4())},
        expected=202,
    )
    verification = request(
        "POST",
        "/v1/onboarding/verify-email",
        body={"email": email, "code": require(signup, "verification_code")},
        headers={"X-Forwarded-For": client_ip, "Idempotency-Key": str(uuid.uuid4())},
    )
    tenant_id = require(verification, "tenant_id")
    bootstrap = require(verification, "api_key")
    promoted = request(
        "POST",
        "/v1/onboarding/promote-bootstrap-key",
        headers={**machine_headers(tenant_id, bootstrap), "Idempotency-Key": str(uuid.uuid4())},
    )
    return tenant_id, require(promoted, "api_key"), email, password


def seed_crm(headers: dict[str, str]) -> None:
    for index in range(1, 4):
        account_id = f"pass3-proof-account-{index}"
        account = {
            "name": f"Pass3 Proof HVAC {index}",
            "company": f"Pass3 Proof HVAC {index}",
            "website": f"https://pass3-proof-hvac-{index}.example.com",
            "domain": f"pass3-proof-hvac-{index}.example.com",
            "industry": "HVAC",
            "location": "Dallas",
            "description": "Commercial HVAC maintenance and installation",
            "automation_opportunity": "Automated lead intake",
            "intent": "Evaluating workflow automation",
        }
        request(
            "PUT",
            f"/v1/crm/records/account/{account_id}",
            body={"data": account},
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        request(
            "PUT",
            f"/v1/crm/records/contact/pass3-proof-contact-{index}",
            body={
                "data": {
                    "name": f"Pass3 Proof Contact {index}",
                    "company": account["company"],
                    "account_id": account_id,
                    "email": f"pass3-proof-contact-{index}@example.com",
                    "phone": f"+1214555010{index}",
                    "role": "Operations Manager",
                }
            },
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )


def main() -> int:
    tenant, machine, email, password = create_tenant()
    machine_auth = machine_headers(tenant, machine)
    seed_crm(machine_auth)
    # A repeated public PUT is the lane's idempotent fixture/retry check.
    seed_crm(machine_auth)

    proposal = request("POST", "/v1/missions/compose", body={"instruction": INSTRUCTION}, headers=machine_auth)
    if proposal.get("ready_to_start") is not True:
        raise ProofFailure(f"composition was not ready: {proposal}")
    plan = proposal.get("planned_steps") or []
    actions = {
        step.get("action_name") or step.get("metadata", {}).get("action") for step in plan if isinstance(step, dict)
    }
    if "web.research" in actions:
        raise ProofFailure("internal CRM mission selected a public discovery action")
    if not {"record.search", "research.observe_contacts", "sales.qualify", "gtm.lead_enrich", "record.write"}.issubset(
        actions
    ):
        raise ProofFailure(f"composition omitted a required internal CRM edge: {actions}")

    confirmed = request(
        "POST",
        f"/v1/missions/proposals/{require(proposal, 'proposal_id')}/confirm",
        body={"idempotency_key": str(uuid.uuid4())},
        headers=machine_auth,
    )
    mission_id = require(confirmed, "mission_id")
    launch = request(
        "POST",
        f"/v1/missions/{mission_id}/launch",
        headers={**machine_auth, "Idempotency-Key": str(uuid.uuid4())},
    )
    pending_ids = launch.get("pending_review_task_ids") or []
    if len(pending_ids) != 1:
        raise ProofFailure(f"expected one pending side-effect task: {launch}")
    task_id = pending_ids[0]

    # A second tenant cannot approve or observe the first tenant's review item.
    other_tenant, other_machine, _, _ = create_tenant()
    other_auth = machine_headers(other_tenant, other_machine)
    status, _ = _request_status(
        "POST",
        f"/v1/review-queue/tasks/{task_id}/approve",
        body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=other_auth,
    )
    if status not in {403, 404}:
        raise ProofFailure(f"cross-tenant review approval was not blocked: {status}")
    status, _ = _request_status("GET", f"/v1/missions/{mission_id}/lifecycle", headers=other_auth)
    if status not in {403, 404}:
        raise ProofFailure(f"cross-tenant lifecycle access was not blocked: {status}")

    status, _ = _request_status(
        "POST",
        f"/v1/review-queue/tasks/{task_id}/approve",
        body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        headers=machine_auth,
    )
    if status != 403:
        raise ProofFailure(f"tenant_operator self-approval was not denied: {status}")

    owner_login = request(
        "POST",
        "/v1/auth/password",
        body={"email": email, "password": password, "tenant_id": tenant},
        headers={"X-Forwarded-For": f"198.51.100.{uuid.uuid4().int % 254 + 1}"},
    )
    owner = {"X-Tenant-Id": tenant, "Authorization": "Bearer " + require(owner_login, "access_token")}
    me = request("GET", "/v1/auth/me", headers=owner)
    if me.get("principal_type") != "user" or "outcome_review:manage" not in me.get("permissions", []):
        raise ProofFailure(f"human reviewer lacks governed review authority: {me}")

    deadline = time.time() + TIMEOUT
    approved = False
    while time.time() < deadline:
        status, _ = _request_status(
            "POST",
            f"/v1/review-queue/tasks/{task_id}/approve",
            body={"approval_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
            headers=owner,
        )
        if status == 200:
            approved = True
            break
        if status != 409:
            raise ProofFailure(f"human approval failed unexpectedly: {status}")
        time.sleep(2)
    if not approved:
        raise ProofFailure("human approval never became dependency-ready")

    while time.time() < deadline:
        lifecycle = request("GET", f"/v1/missions/{mission_id}/lifecycle", headers=machine_auth)
        if lifecycle.get("mission", {}).get("status") in {"completed", "failed"}:
            break
        time.sleep(2)
    evidence = request("GET", f"/v1/missions/{mission_id}/runtime-evidence", headers=machine_auth)
    deliverable = request("GET", f"/v1/missions/{mission_id}/deliverable", headers=machine_auth)
    if lifecycle.get("mission", {}).get("status") != "completed":
        raise ProofFailure(f"mission did not complete: {lifecycle}")
    reconciliation = (
        lifecycle.get("intake", {})
        .get("context", {})
        .get("composition", {})
        .get("deliverable_runtime_state", {})
        .get("runtime_reconciliation", {})
    )
    if reconciliation.get("status") != "aligned" or reconciliation.get("structural_status") != "aligned":
        raise ProofFailure(f"runtime reconciliation was not aligned: {reconciliation}")
    if reconciliation.get("semantic_status") != "aligned" or reconciliation.get("first_divergence") is not None:
        raise ProofFailure(f"semantic reconciliation was not aligned: {reconciliation}")
    if reconciliation.get("contradiction_codes") or evidence.get("contradictions"):
        raise ProofFailure(f"runtime contradictions were reported: {reconciliation}")
    if evidence.get("first_divergence") is not None:
        raise ProofFailure(f"runtime first divergence was reported: {evidence['first_divergence']}")
    if evidence.get("acceptance", {}).get("status") != "met":
        raise ProofFailure(f"acceptance did not pass: {evidence.get('acceptance')}")
    if deliverable.get("completion", {}).get("complete") is not True:
        raise ProofFailure(f"deliverable did not complete: {deliverable}")
    prospects = deliverable.get("prospects")
    if not isinstance(prospects, list) or len(prospects) != 3:
        raise ProofFailure(f"customer artifact has wrong prospect count: {prospects}")
    for prospect in prospects:
        for field in ("company_name", "website", "qualification_score", "qualification_evidence"):
            if not prospect.get(field):
                raise ProofFailure(f"customer artifact omitted {field}: {prospect}")

    records = request("GET", "/v1/crm/records?record_type=contact", headers=machine_auth).get("items", [])
    ids = [
        item.get("id")
        for item in records
        if isinstance(item, dict) and str(item.get("id", "")).startswith("pass3-proof-contact-")
    ]
    if len(ids) != 3 or len(set(ids)) != 3:
        raise ProofFailure(f"CRM retry/read-back created duplicate or missing contacts: {ids}")
    print(json.dumps({"pass3": "success", "tenant_id": tenant, "mission_id": mission_id}, indent=2))
    return 0


def _request_status(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    """Return status for expected cross-tenant denials without hiding payloads."""
    method, path = args[:2]
    body = kwargs.get("body")
    headers = kwargs.get("headers")
    payload = json.dumps(body).encode() if body is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_obj = urllib.request.Request(BASE + path, data=payload, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


if __name__ == "__main__":
    raise SystemExit(main())
