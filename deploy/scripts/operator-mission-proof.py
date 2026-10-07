#!/usr/bin/env python3
"""Prove the real operator mission path against a running staging stack.

This proof intentionally uses only the public onboarding, composition,
confirmation, launch, lifecycle, and deliverable APIs. It must never create
database rows or invoke a worker handler directly.
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

API_BASE = os.environ.get("AJENDA_OPERATOR_PROOF_API_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_BASE = os.environ.get("AJENDA_OPERATOR_PROOF_FRONTEND_BASE_URL", "http://localhost:8080").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("AJENDA_OPERATOR_PROOF_TIMEOUT_SECONDS", "180"))
POLL_SECONDS = float(os.environ.get("AJENDA_OPERATOR_PROOF_POLL_SECONDS", "3"))
SCENARIO = os.environ.get("AJENDA_OPERATOR_PROOF_SCENARIO", "baseline").strip()
PASS3_SCENARIO = "pass3_internal_crm"
DEFAULT_INSTRUCTION = (
    "Review the three HVAC companies already saved in Ajenda internal CRM, qualify them, "
    "enrich the contacts, persist the qualified prospects to Ajenda internal CRM, and return "
    "company name, website, qualification score, and qualification evidence for each. "
    "Read back every saved record. Do not send messages."
    if SCENARIO == PASS3_SCENARIO
    else "Find five software development companies in Austin using local fixture data only."
)
INSTRUCTION = os.environ.get("AJENDA_OPERATOR_PROOF_INSTRUCTION", DEFAULT_INSTRUCTION)
EXPECTED_PROSPECT_COUNT = int(
    os.environ.get(
        "AJENDA_OPERATOR_PROOF_EXPECTED_PROSPECT_COUNT",
        "3" if SCENARIO == PASS3_SCENARIO else "5",
    )
)
RUNTIME_EVIDENCE_OUTPUT = os.environ.get("AJENDA_OPERATOR_PROOF_RUNTIME_EVIDENCE_OUTPUT")


class ProofFailure(RuntimeError):
    """Raised when an operator proof invariant is not satisfied."""


def request(
    method: str,
    base: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected: int | tuple[int, ...] = 200,
) -> dict[str, Any]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request_obj = urllib.request.Request(f"{base}{path}", data=payload, headers=request_headers, method=method)
    allowed = (expected,) if isinstance(expected, int) else expected
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            status = response.status
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8")
    if status not in allowed:
        raise ProofFailure(f"{method} {path} returned HTTP {status}: {raw}")
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ProofFailure(f"{method} {path} returned a non-object JSON response")
    return value


def auth(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def human_auth(tenant_id: str, access_token: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "Authorization": f"Bearer {access_token}"}


def require_string(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProofFailure(f"{context} missing non-empty {key}")
    return value.strip()


def create_tenant_session(*, org_name: str) -> tuple[str, str, str]:
    """Create machine execution plus independent human-review authority."""

    email = f"operator-proof-{uuid.uuid4().hex[:10]}@example.com"
    owner_password = f"Proof-{uuid.uuid4().hex}-Aa1!"
    signup = request(
        "POST",
        API_BASE,
        "/v1/onboarding/signup",
        body={"org_name": org_name, "email": email, "password": owner_password},
        headers={"Idempotency-Key": str(uuid.uuid4())},
        expected=(201, 202),
    )
    if not signup.get("verification_code"):
        raise ProofFailure(
            "signup omitted verification_code; staging proof requires "
            "AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=true or a test mailbox delivery path"
        )
    verification_code = require_string(signup, "verification_code", "signup")
    verification = request(
        "POST",
        API_BASE,
        "/v1/onboarding/verify-email",
        body={"email": email, "code": verification_code},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    tenant_id = require_string(verification, "tenant_id", "email verification")
    bootstrap_key = require_string(verification, "api_key", "email verification")
    promoted = request(
        "POST",
        API_BASE,
        "/v1/onboarding/promote-bootstrap-key",
        headers={**auth(tenant_id, bootstrap_key), "Idempotency-Key": str(uuid.uuid4())},
    )
    api_key = require_string(promoted, "api_key", "bootstrap promotion")
    login = request(
        "POST",
        API_BASE,
        "/v1/auth/password",
        body={"email": email, "password": owner_password, "tenant_id": tenant_id},
    )
    access_token = require_string(login, "access_token", "tenant-owner password login")
    me = request("GET", API_BASE, "/v1/auth/me", headers=human_auth(tenant_id, access_token))
    permissions = {str(item) for item in (me.get("permissions") or [])}
    if me.get("principal_type") != "user" or "outcome_review:manage" not in permissions:
        raise ProofFailure(
            "password login did not yield an independently authorized human reviewer: "
            f"{json.dumps(me, sort_keys=True)}"
        )
    return tenant_id, api_key, access_token


def assert_blocked_composition(
    *,
    headers: dict[str, str],
    instruction: str,
    expected_status: str,
) -> None:
    """Prove unsupported/over-capacity requests stop before runtime authority."""

    proposal = request(
        "POST",
        API_BASE,
        "/v1/missions/compose",
        body={"instruction": instruction},
        headers=headers,
    )
    coverage = proposal.get("coverage_assessment")
    if not isinstance(coverage, dict):
        raise ProofFailure(f"blocked composition omitted coverage assessment: {json.dumps(proposal, sort_keys=True)}")
    if coverage.get("status") != expected_status:
        raise ProofFailure(
            f"blocked composition expected coverage {expected_status!r}, "
            f"got {coverage.get('status')!r}: {json.dumps(proposal, sort_keys=True)}"
        )
    if coverage.get("grants_execution_authority") is not False:
        raise ProofFailure("blocked coverage assessment granted execution authority")
    if proposal.get("ready_to_start") is not False:
        raise ProofFailure(f"blocked composition became ready to start: {json.dumps(proposal, sort_keys=True)}")


def seed_internal_crm_fixture(*, api_base: str, headers: dict[str, str]) -> None:
    """Create proof-owned CRM rows through the public CRM API.

    The operator proof must exercise the same tenant-scoped write boundary as
    a real operator. It must not insert rows directly into Postgres.
    """

    for index in range(1, 4):
        company = f"Operator Proof HVAC {index}"
        request(
            "PUT",
            api_base,
            f"/v1/crm/records/account/operator-proof-hvac-{index}",
            body={
                "data": {
                    "name": company,
                    "company": company,
                    "website": f"https://operator-proof-hvac-{index}.example.com",
                    "domain": f"operator-proof-hvac-{index}.example.com",
                    "industry": "HVAC",
                    "location": "Dallas",
                    "description": "Commercial HVAC maintenance and installation",
                    "automation_opportunity": "Automated lead intake and service follow-up",
                    "intent": "Evaluating workflow automation",
                }
            },
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )
        request(
            "PUT",
            api_base,
            f"/v1/crm/records/contact/operator-proof-hvac-contact-{index}",
            body={
                "data": {
                    "name": f"Owner {index}",
                    "company": company,
                    "account_id": f"operator-proof-hvac-{index}",
                    "email": f"owner{index}@operator-proof-hvac-{index}.example.com",
                    "role": "Owner",
                    "source": "operator_proof",
                    "real": True,
                }
            },
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )


def approve_pending_pass3_tasks(
    *,
    tenant_id: str,
    machine_headers: dict[str, str],
    owner_headers: dict[str, str],
    mission_id: str,
    approved_task_ids: set[str],
) -> None:
    """Exercise independent human approval without expanding machine authority."""

    queue = request("GET", API_BASE, "/v1/review-queue/tasks", headers=owner_headers)
    for item in queue.get("items") or []:
        if not isinstance(item, dict) or str(item.get("mission_id") or "") != mission_id:
            continue
        task_id = str(item.get("task_id") or "").strip()
        if not task_id or task_id in approved_task_ids:
            continue

        approval_body = {
            "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        }

        denied = request(
            "POST",
            API_BASE,
            f"/v1/review-queue/tasks/{task_id}/approve",
            body=approval_body,
            headers=machine_headers,
            expected=403,
        )
        if "permission" not in json.dumps(denied).lower():
            raise ProofFailure(f"machine approval denial did not expose an authorization reason: {denied}")

        approved = request(
            "POST",
            API_BASE,
            f"/v1/review-queue/tasks/{task_id}/approve",
            body=approval_body,
            headers=owner_headers,
            expected=(200, 409),
        )
        detail = str(approved.get("detail") or "")
        if "dependencies not complete" in detail:
            # Review is visible before its prerequisite tasks necessarily
            # finish. Keep polling; approval must bind only after the governed
            # upstream world-state is complete.
            continue
        if approved.get("status") != "queued":
            raise ProofFailure(f"tenant-owner approval did not queue reviewed task {task_id}: {approved}")
        approved_task_ids.add(task_id)


def main() -> int:
    frontend = urllib.request.urlopen(f"{FRONTEND_BASE}/", timeout=30).read().decode("utf-8")
    if 'id="root"' not in frontend:
        raise ProofFailure("frontend root page did not contain the SPA mount point")

    tenant_id, api_key, owner_access_token = create_tenant_session(org_name="Ajenda Operator Proof")
    headers = auth(tenant_id, api_key)
    owner_headers = human_auth(tenant_id, owner_access_token)

    assert_blocked_composition(
        headers=headers,
        instruction="Find three dental companies in Seattle using local fixture data only.",
        expected_status="unsupported_scope",
    )
    assert_blocked_composition(
        headers=headers,
        instruction="Find five HVAC companies in Dallas using local fixture data only.",
        expected_status="insufficient_capacity",
    )

    if "internal crm" in INSTRUCTION.lower():
        seed_internal_crm_fixture(api_base=API_BASE, headers=headers)

    proposal = request(
        "POST",
        API_BASE,
        "/v1/missions/compose",
        body={"instruction": INSTRUCTION},
        headers=headers,
    )
    proposal_id = require_string(proposal, "proposal_id", "composition")
    if proposal.get("ready_to_start") is not True:
        raise ProofFailure(f"complete HVAC request was not ready: {json.dumps(proposal, sort_keys=True)}")
    if proposal.get("missing_connections"):
        raise ProofFailure(f"HVAC request has missing connections: {proposal['missing_connections']}")

    confirmed = request(
        "POST",
        API_BASE,
        f"/v1/missions/proposals/{proposal_id}/confirm",
        body={"idempotency_key": str(uuid.uuid4())},
        headers=headers,
    )
    mission_id = require_string(confirmed, "mission_id", "confirmation")
    if confirmed.get("runtime_queued") is not False:
        raise ProofFailure("confirmation granted runtime queue authority")

    launched = request(
        "POST",
        API_BASE,
        f"/v1/missions/{mission_id}/launch",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    queued_task_ids = launched.get("queued_task_ids")
    if not isinstance(queued_task_ids, list) or not queued_task_ids:
        raise ProofFailure(f"launch returned no queued task IDs: {json.dumps(launched, sort_keys=True)}")
    blockers = launched.get("blockers") or []
    if blockers:
        if SCENARIO != PASS3_SCENARIO:
            raise ProofFailure(f"launch returned blockers: {blockers}")
        unexpected = [
            item
            for item in blockers
            if not isinstance(item, dict)
            or item.get("code") != "policy_review_required"
            or item.get("state") != "pending_review"
        ]
        if unexpected:
            raise ProofFailure(f"Pass 3 launch returned unexpected blockers: {unexpected}")
        pending_review_task_ids = launched.get("pending_review_task_ids") or []
        blocked_task_ids = {
            str(item.get("task_id") or "")
            for item in blockers
            if isinstance(item, dict) and item.get("task_id")
        }
        if not blocked_task_ids or blocked_task_ids != {str(item) for item in pending_review_task_ids}:
            raise ProofFailure(
                "Pass 3 launch did not expose the reviewed task consistently across blockers and pending_review_task_ids: "
                f"{json.dumps(launched, sort_keys=True)}"
            )

    deadline = time.monotonic() + TIMEOUT_SECONDS
    approved_task_ids: set[str] = set()
    deliverable: dict[str, Any] | None = None
    lifecycle: dict[str, Any] | None = None
    runtime_evidence: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        lifecycle = request("GET", API_BASE, f"/v1/missions/{mission_id}/lifecycle", headers=headers)
        runtime_evidence = request("GET", API_BASE, f"/v1/missions/{mission_id}/runtime-evidence", headers=headers)
        if SCENARIO == PASS3_SCENARIO:
            approve_pending_pass3_tasks(
                tenant_id=tenant_id,
                machine_headers=headers,
                owner_headers=owner_headers,
                mission_id=mission_id,
                approved_task_ids=approved_task_ids,
            )
        mission_state = (lifecycle.get("mission") or {}).get("status")
        if mission_state in {"failed", "blocked", "cancelled", "dead_lettered"}:
            if RUNTIME_EVIDENCE_OUTPUT:
                output = Path(RUNTIME_EVIDENCE_OUTPUT)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(runtime_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            raise ProofFailure(
                "mission reached terminal failure before deliverable: "
                f"status={mission_state} lifecycle={json.dumps(lifecycle, sort_keys=True)} "
                f"runtime_evidence={json.dumps(runtime_evidence, sort_keys=True)}"
            )
        try:
            candidate = request("GET", API_BASE, f"/v1/missions/{mission_id}/deliverable", headers=headers)
        except ProofFailure as exc:
            if "HTTP 404" not in str(exc):
                raise
            candidate = None
        if candidate is not None:
            task_state = candidate.get("task_state") or {}
            completion = candidate.get("completion") or {}
            statuses = task_state.get("statuses") or {}
            if statuses.get("queued") or statuses.get("running") or not task_state.get("all_terminal"):
                time.sleep(POLL_SECONDS)
                continue
            # Deliverable projection and mission lifecycle are persisted by
            # separate runtime updates.  A terminal task can briefly precede
            # the mission status transition, so do not treat this snapshot as
            # proof until the freshly-read lifecycle is terminal too.
            mission_state = (lifecycle.get("mission") or {}).get("status") if lifecycle else None
            if mission_state != "completed":
                time.sleep(POLL_SECONDS)
                continue
            deliverable = candidate
            break
        time.sleep(POLL_SECONDS)

    if deliverable is None:
        raise ProofFailure(
            "mission did not produce a terminal deliverable: "
            f"lifecycle={json.dumps(lifecycle, sort_keys=True)} "
            f"runtime_evidence={json.dumps(runtime_evidence, sort_keys=True)}"
        )
    task_state = deliverable.get("task_state") or {}
    completion = deliverable.get("completion") or {}
    prospects = deliverable.get("prospects")
    if RUNTIME_EVIDENCE_OUTPUT:
        output = Path(RUNTIME_EVIDENCE_OUTPUT)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(runtime_evidence or {}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    mission_status = (lifecycle or {}).get("mission", {}).get("status") or (runtime_evidence or {}).get(
        "mission_status"
    )
    acceptance = (lifecycle or {}).get("mission", {}).get("acceptance") or (runtime_evidence or {}).get("acceptance")
    if mission_status != "completed":
        raise ProofFailure(f"mission did not complete acceptance: status={mission_status!r} acceptance={acceptance}")

    mission_read = request("GET", API_BASE, f"/v1/missions/{mission_id}", headers=headers)
    runtime_state = mission_read.get("deliverable_runtime_state")
    if not isinstance(runtime_state, dict):
        raise ProofFailure("completed mission omitted deliverable runtime state")
    reconciliation = runtime_state.get("runtime_reconciliation")
    if not isinstance(reconciliation, dict):
        raise ProofFailure("completed mission omitted runtime reconciliation")
    if reconciliation.get("status") != "aligned":
        raise ProofFailure(f"shadow/runtime reconciliation was not aligned: {json.dumps(reconciliation, sort_keys=True)}")
    if reconciliation.get("grants_execution_authority") is not False:
        raise ProofFailure("runtime reconciliation granted execution authority")
    if reconciliation.get("semantic_mismatch_codes"):
        raise ProofFailure(f"semantic reconciliation reported contradictions: {reconciliation['semantic_mismatch_codes']}")
    if reconciliation.get("semantic_drift_codes"):
        raise ProofFailure(f"semantic reconciliation reported unexplained drift: {reconciliation['semantic_drift_codes']}")

    contradictions = (runtime_evidence or {}).get("contradictions", [])
    if contradictions:
        raise ProofFailure(f"runtime evidence reported contradictions: {contradictions}")
    if (runtime_evidence or {}).get("first_divergence") is not None:
        raise ProofFailure(
            f"runtime evidence reported first divergence: {(runtime_evidence or {}).get('first_divergence')}"
        )

    other_tenant_id, other_api_key, _ = create_tenant_session(org_name="Ajenda Operator Proof Isolation")
    _ = request(
        "GET",
        API_BASE,
        f"/v1/missions/{mission_id}/runtime-evidence",
        headers=auth(other_tenant_id, other_api_key),
        expected=404,
    )

    if SCENARIO == PASS3_SCENARIO and not approved_task_ids:
        raise ProofFailure("Pass 3 mission never exercised the independent side-effect approval boundary")
    if task_state.get("all_succeeded") is not True:
        raise ProofFailure(f"mission tasks did not all succeed: {task_state}")
    if completion.get("artifact_complete") is not True or completion.get("complete") is not True:
        raise ProofFailure(f"deliverable is incomplete: {completion}")
    if not isinstance(prospects, list) or len(prospects) != EXPECTED_PROSPECT_COUNT:
        raise ProofFailure(
            f"expected exactly {EXPECTED_PROSPECT_COUNT} persisted prospects, "
            f"got {len(prospects) if isinstance(prospects, list) else prospects}"
        )
    if any(not isinstance(row, dict) or not row.get("company_name") or not row.get("website") for row in prospects):
        raise ProofFailure("one or more prospects lacks a company name or website")

    print(
        json.dumps(
            {
                "ok": True,
                "scenario": SCENARIO,
                "instruction": INSTRUCTION,
                "tenant_id": tenant_id,
                "proposal_id": proposal_id,
                "mission_id": mission_id,
                "task_ids": [str(item) for item in queued_task_ids],
                "prospect_count": len(prospects),
                "evidence_count": len(deliverable.get("evidence_references") or []),
                "mission_status": mission_status,
                "runtime_evidence_first_divergence": (runtime_evidence or {}).get("first_divergence"),
                "runtime_evidence_contradictions": (runtime_evidence or {}).get("contradictions", []),
                "runtime_reconciliation_status": reconciliation.get("status"),
                "runtime_reconciliation_semantic_status": reconciliation.get("semantic_status"),
                "blocked_coverage_cases": ["unsupported_scope", "insufficient_capacity"],
                "cross_tenant_runtime_evidence_denied": True,
                "independent_human_approval_task_ids": sorted(approved_task_ids),
                "runtime_evidence_output": RUNTIME_EVIDENCE_OUTPUT,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProofFailure, urllib.error.URLError) as exc:
        raise SystemExit(f"operator mission proof failed: {exc}") from exc
