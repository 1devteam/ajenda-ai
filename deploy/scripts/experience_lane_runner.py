#!/usr/bin/env python3
"""Run 12 varied live tasks through the tool.invoke runtime spine (PRIDE protocol)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

API_BASE = os.environ.get("AJENDA_PROOF_API_BASE_URL", "http://localhost:8000").rstrip("/")
COMPOSE_FILE = os.environ.get("AJENDA_PROOF_COMPOSE_FILE", "deploy/compose/docker-compose.prod.yml")
COMPOSE_ENV_FILE = os.environ.get("AJENDA_PROOF_COMPOSE_ENV_FILE", "deploy/compose/.env.prod")
TOTAL_TASKS = 12


def log(message: str) -> None:
    print(f"[experience-lane] {message}", flush=True)


def request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    expected: int | tuple[int, ...] = 200,
) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    payload = None
    if body is not None:
        payload = json.dumps(body).encode()
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{API_BASE}{path}", data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode()
        allowed = expected if isinstance(expected, tuple) else (expected,)
        if status not in allowed:
            raise RuntimeError(f"{method} {path} -> {status}: {raw}")
        return json.loads(raw) if raw else {}
    allowed = expected if isinstance(expected, tuple) else (expected,)
    if status not in allowed:
        raise RuntimeError(f"{method} {path} -> {status}: {raw}")
    return json.loads(raw) if raw else {}


def auth_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def resolve_hubspot_token() -> str:
    env = os.environ.get("AJENDA_E2E_HUBSPOT_PAK", "").strip()
    if env:
        return env
    import yaml

    cfg = yaml.safe_load((Path.home() / ".hscli" / "config.yml").read_text(encoding="utf-8"))
    for account in cfg.get("accounts", []):
        auth = account.get("auth") or {}
        token_info = auth.get("tokenInfo") or {}
        token = token_info.get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()
        pak = account.get("personalAccessKey")
        if isinstance(pak, str) and pak.strip():
            return pak.strip()
    raise RuntimeError("missing HubSpot token")


def provision_tenant() -> tuple[str, str]:
    email = f"experience-{uuid.uuid4().hex[:10]}@example.com"
    signup = request(
        "POST",
        "/v1/onboarding/signup",
        body={"org_name": "Experience Pilot Co", "email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
        expected=201,
    )
    tenant_id = signup["tenant_id"]
    verify = request(
        "POST",
        "/v1/onboarding/verify-email",
        body={"token": signup["verification_token"]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
        expected=200,
    )
    promote = request(
        "POST",
        "/v1/onboarding/promote-bootstrap-key",
        headers={**auth_headers(tenant_id, verify["api_key"]), "Idempotency-Key": str(uuid.uuid4())},
        expected=200,
    )
    return tenant_id, promote["api_key"]


def assert_pride_gate(spec: dict[str, Any], item: dict[str, Any]) -> None:
    """Fail closed when a lane does not meet live-runtime PRIDE expectations."""
    output = item.get("output") or {}
    action = spec["action"]
    lane = spec.get("lane", "")
    summary = item.get("summary") or ""

    if "simulated" in json.dumps(output).lower():
        raise RuntimeError(f"{action}: simulated output forbidden")

    if action == "web.search":
        if not output.get("search_real"):
            raise RuntimeError("web.search: search_real must be true")
        if int(output.get("web_result_count") or 0) < 1:
            raise RuntimeError("web.search: expected at least one public result")

    if action == "crm.research" and lane.startswith("api-hubspot"):
        if "via external plugin" not in summary:
            raise RuntimeError("crm.research: expected live HubSpot adapter summary")
        if output.get("source") not in {"hubspot", "external_crm"}:
            raise RuntimeError(f"crm.research: unexpected source {output.get('source')!r}")
        if not output.get("plugin_required"):
            raise RuntimeError("crm.research: plugin_required must be true")
        matches = output.get("crm_matches") or []
        if len(matches) < 1:
            raise RuntimeError("crm.research: expected at least one CRM match")
        expected_id = spec.get("expected_record_id")
        if expected_id:
            match_ids = {str(match.get("id")) for match in matches if isinstance(match, dict)}
            if str(expected_id) not in match_ids:
                raise RuntimeError(f"crm.research: expected HubSpot record id {expected_id!r} in matches")

    if action == "gtm.crm_upsert":
        if output.get("status") != "upserted_real":
            raise RuntimeError(f"gtm.crm_upsert: expected upserted_real, got {output.get('status')!r}")
        if not output.get("plugin_required"):
            raise RuntimeError("gtm.crm_upsert: plugin_required must be true")
        if output.get("source") not in {"hubspot", "external_crm"}:
            raise RuntimeError(f"gtm.crm_upsert: unexpected source {output.get('source')!r}")
        if not str(output.get("id") or "").strip():
            raise RuntimeError("gtm.crm_upsert: expected non-empty HubSpot record id")

    if action == "gtm.email_check":
        emails = output.get("emails") or []
        if len(emails) < 1:
            raise RuntimeError("gtm.email_check: expected inbox messages")
        if emails[0].get("id") == "sim-1":
            raise RuntimeError("gtm.email_check: simulated message id forbidden")


def upgrade_tenant_plan(tenant_id: str, plan: str = "pro") -> None:
    script = """
import sys, uuid
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.tenant import Tenant

tenant_id, plan = sys.argv[1], sys.argv[2]
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
    proc = subprocess.run(
        [
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
        ],
        input=script.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode() or "plan upgrade failed")


def run_task_sync(tenant_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Execute one task in an isolated API container process (avoids DB pool leaks)."""
    payload = json.dumps(spec)
    worker = r'''
import json, os, uuid
from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.workers.handlers.tool_invoke import tool_invoke_handler

tenant_id = os.environ["AJENDA_EXP_TENANT_ID"]
spec = json.loads(os.environ["AJENDA_EXP_SPEC"])
action = spec["action"]
side_effect = spec.get("side_effect_class", "none")
adapter_class = spec.get("adapter_classification") or {
    "none": "none",
    "internal_write": "non_idempotent_write",
    "external_read": "external_read",
    "external_write": "external_write",
}.get(side_effect, "none")

settings = get_settings()
runtime = DatabaseRuntime(settings)
try:
    session = runtime.session_factory()
    try:
        capability = None
        adapter = None
        needs_authority = side_effect != "none" or action.startswith("gtm.") or action.startswith("crm.")
        if needs_authority:
            suffix = uuid.uuid4().hex[:10]
            approval_required = adapter_class in {
                "external_write",
                "external_side_effect",
                "external_send",
                "external_publish",
            }
            capability = Capability(
                tenant_id=tenant_id,
                name=f"experience-{action}-{suffix}",
                version="1.0.0",
                description=f"Experience lane for {action}",
                supported_task_types=["tool.invoke", action],
                input_schema_hints={},
                output_schema_hints={},
                required_permissions=[],
                required_tools=[action],
                risk_level="medium",
                approval_requirements={"required": approval_required, "generated_by": "experience-lane"},
                evidence_expectations=[f"{action} evidence"],
                execution_constraints={},
                enabled=True,
                schema_version=1,
            )
            session.add(capability)
            session.flush()
            adapter = CapabilityAdapter(
                tenant_id=tenant_id,
                name=f"experience-{action}-adapter-{suffix}",
                version="1.0.0",
                capability_id=capability.id,
                capability_name=capability.name,
                capability_version=capability.version,
                supported_task_types=["tool.invoke", action],
                input_contract={},
                output_contract={},
                required_permissions=[],
                required_tools=[action],
                execution_mode="queued",
                risk_level="medium",
                approval_requirements={"required": approval_required, "generated_by": "experience-lane"},
                evidence_expectations=[f"{action} evidence"],
                timeout_retry_hints={},
                idempotency_expectations={},
                side_effect_classification=adapter_class,
                enabled=True,
                schema_version=1,
            )
            session.add(adapter)
            session.flush()

        mission = Mission(tenant_id=tenant_id, objective=spec["label"], status="running")
        session.add(mission)
        session.flush()
        tool_invocation = {
            "schema_version": 1,
            "action": action,
            "input": spec.get("input", {}),
        }
        if spec.get("idempotency_key"):
            tool_invocation["idempotency_key"] = spec["idempotency_key"]
        metadata = {
            "task_type": "tool.invoke",
            "launched_by": "experience-lane",
            "tool_invocation": tool_invocation,
        }
        if capability is not None:
            metadata["capability_reference"] = {"capability_id": str(capability.id)}
        if adapter is not None:
            metadata["adapter_reference"] = {"adapter_id": str(adapter.id)}
        if spec.get("credential_reference"):
            metadata["credential_reference"] = spec["credential_reference"]
        if side_effect in {"internal_write", "external_write", "external_send", "external_publish"}:
            metadata["execution_constraints"] = {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": [action],
                    "reason": "experience-lane",
                    "approved_by": "experience-pilot",
                }
            }
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=spec["label"],
            description="experience-lane sync",
            status=ExecutionTaskState.RUNNING.value,
            metadata_json=metadata,
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        session.add(task)
        session.flush()
        task_id = task.id
        session.commit()
    finally:
        session.close()

    ctx = {
        "worker_id": "experience-lane",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": runtime.session_factory,
    }
    session = runtime.session_factory()
    try:
        current = session.get(ExecutionTask, task_id)
        result = tool_invoke_handler(current, ctx)
        current.status = ExecutionTaskState.COMPLETED.value
        current.metadata_json = {**current.metadata_json, "output": result.get("output"), "handler_result": result}
        session.commit()
        print(
            json.dumps(
                {
                    "label": spec["label"],
                    "action": action,
                    "task_id": str(task_id),
                    "status": "completed",
                    "summary": result.get("summary"),
                    "lane": spec.get("lane", "sync-runtime"),
                    "output": result.get("output"),
                }
            )
        )
    except Exception as exc:
        session.rollback()
        session = runtime.session_factory()
        current = session.get(ExecutionTask, task_id)
        if current is not None:
            current.status = ExecutionTaskState.FAILED.value
            session.commit()
        raise RuntimeError(f"{action} failed: {exc}") from exc
    finally:
        session.close()
finally:
    runtime.dispose()
'''
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            COMPOSE_ENV_FILE,
            "-f",
            COMPOSE_FILE,
            "exec",
            "-T",
            "-e",
            f"AJENDA_EXP_TENANT_ID={tenant_id}",
            "-e",
            f"AJENDA_EXP_SPEC={payload}",
            "api",
            "python",
            "-",
        ],
        input=worker.encode(),
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode() or proc.stdout.decode())
    line = proc.stdout.decode().strip().splitlines()[-1]
    return json.loads(line)


def run_task_with_optional_readback_retry(tenant_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("lane") != "api-hubspot-readback":
        return run_task_sync(tenant_id, spec)
    last_item: dict[str, Any] | None = None
    for attempt in range(5):
        last_item = run_task_sync(tenant_id, spec)
        matches = (last_item.get("output") or {}).get("crm_matches") or []
        if matches:
            return last_item
        if attempt < 4:
            time.sleep(1.5)
    assert last_item is not None
    return last_item


def main() -> int:
    gmail_token = os.environ.get("AJENDA_E2E_GMAIL_TOKEN", "").strip()
    if not gmail_token:
        raise RuntimeError("Gmail token missing; run: python scripts/google/gmail_cli_auth.py token")

    hubspot_token = resolve_hubspot_token()
    tenant_id, api_key = provision_tenant()
    auth = auth_headers(tenant_id, api_key)
    upgrade_tenant_plan(tenant_id, "pro")

    hubspot_adapter_host = os.environ.get(
        "AJENDA_E2E_ADAPTER_HOST",
        os.environ.get("AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST", "hubspot-crm-ingress"),
    )
    for cred in [
        {
            "credential_id": "hubspot-crm",
            "provider": "external_crm",
            "integration": "hubspot",
            "secret_value": hubspot_token,
            "trusted_destination_hosts": [hubspot_adapter_host],
        },
        {
            "credential_id": "gmail-email",
            "provider": "external_email",
            "integration": "gmail",
            "secret_value": gmail_token,
        },
    ]:
        request("POST", "/v1/account/provider-credentials", headers=auth, body=cred, expected=201)

    log(f"tenant_id={tenant_id} (pro plan, credentials registered)")
    log("Gmail OAuth token refreshed")

    crm_ref = {
        "schema_version": 1,
        "credential_id": "hubspot-crm",
        "provider": "external_crm",
        "credential_type": "api_key",
    }
    gmail_ref = {
        "schema_version": 1,
        "credential_id": "gmail-email",
        "provider": "external_email",
        "credential_type": "api_key",
    }

    pride_suffix = uuid.uuid4().hex[:8]
    pride_company = f"PRIDE Proof {pride_suffix}"
    pride_domain = f"pride-{pride_suffix}.example"

    specs = [
        {
            "label": "1/12 seed account",
            "action": "record.write",
            "side_effect_class": "internal_write",
            "input": {"record_type": "account", "data": {"name": "Acme Robotics", "domain": "acmerobotics.example"}},
            "lane": "brain-internal",
        },
        {
            "label": "2/12 web research",
            "action": "web.research",
            "side_effect_class": "none",
            "input": {
                "query": "Acme Robotics",
                "company": "Acme Robotics",
                "domain": "wikipedia.org",
                "fetch_public_page": True,
                "limit": 5,
            },
            "lane": "brain-web",
        },
        {
            "label": "3/12 web search",
            "action": "web.search",
            "side_effect_class": "external_read",
            "adapter_classification": "external_read",
            "input": {"query": "HubSpot", "limit": 5},
            "lane": "brain-egress",
        },
        {
            "label": "4/12 sales research",
            "action": "sales.research",
            "side_effect_class": "none",
            "input": {"lead": {"company": "Acme Robotics", "domain": "acmerobotics.example"}},
            "lane": "brain-sales",
        },
        {
            "label": "5/12 qualify lead",
            "action": "sales.qualify",
            "side_effect_class": "none",
            "input": {"lead": {"company": "Acme Robotics", "title": "VP Engineering"}},
            "lane": "brain-sales",
        },
        {
            "label": "6/12 record search",
            "action": "record.search",
            "side_effect_class": "none",
            "input": {"record_type": "account", "query": "Acme", "limit": 5},
            "lane": "brain-internal",
        },
        {
            "label": "7/12 enrich lead",
            "action": "gtm.lead_enrich",
            "side_effect_class": "none",
            "input": {"company": "Acme Robotics", "domain": "acmerobotics.example"},
            "lane": "brain-gtm",
        },
        {
            "label": "8/12 log activity",
            "action": "sales.log_activity",
            "side_effect_class": "internal_write",
            "input": {
                "record_type": "activity",
                "data": {"company": "Acme Robotics", "activity_type": "call", "notes": "Discovery call"},
            },
            "lane": "brain-internal",
        },
        {
            "label": "9/12 HubSpot CRM research",
            "action": "crm.research",
            "side_effect_class": "none",
            "input": {"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
            "credential_reference": crm_ref,
            "lane": "api-hubspot",
        },
        {
            "label": "10/12 Gmail inbox check",
            "action": "gtm.email_check",
            "side_effect_class": "external_read",
            "adapter_classification": "external_read",
            "input": {"query": "in:inbox", "limit": 3},
            "credential_reference": gmail_ref,
            "lane": "api-gmail",
        },
        {
            "label": "11/12 HubSpot CRM upsert",
            "action": "gtm.crm_upsert",
            "side_effect_class": "internal_write",
            "adapter_classification": "non_idempotent_write",
            "idempotency_key": f"pride-upsert-{pride_suffix}",
            "input": {
                "record_type": "company",
                "data": {"name": pride_company, "domain": pride_domain},
            },
            "credential_reference": crm_ref,
            "lane": "api-hubspot-write",
        },
        {
            "label": "12/12 HubSpot CRM read-back",
            "action": "crm.research",
            "side_effect_class": "none",
            "input": {"lead": {"company": pride_company, "domain": pride_domain}},
            "credential_reference": crm_ref,
            "lane": "api-hubspot-readback",
        },
    ]

    results: list[dict[str, Any]] = []
    batch_started = time.monotonic()
    for spec in specs:
        run_spec = dict(spec)
        if run_spec.get("lane") == "api-hubspot-readback":
            for prior in reversed(results):
                if prior.get("action") == "gtm.crm_upsert":
                    run_spec["expected_record_id"] = (prior.get("output") or {}).get("id")
                    break
        log(f"{run_spec['label']} ({run_spec['action']})...")
        task_started = time.monotonic()
        try:
            item = run_task_with_optional_readback_retry(tenant_id, run_spec)
            item["elapsed_s"] = round(time.monotonic() - task_started, 2)
            assert_pride_gate(run_spec, item)
            results.append(item)
            log(f"  OK {item['task_id']} in {item['elapsed_s']}s — {item.get('summary', '')[:80]}")
        except Exception as exc:
            log(f"  FAIL: {exc}")
            print(
                json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "passed": len(results),
                        "total": TOTAL_TASKS,
                        "elapsed_s": round(time.monotonic() - batch_started, 2),
                        "results": results,
                    },
                    indent=2,
                )
            )
            return 1

    total_elapsed = round(time.monotonic() - batch_started, 2)
    print(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "passed": len(results),
                "total": TOTAL_TASKS,
                "elapsed_s": total_elapsed,
                "results": results,
            },
            indent=2,
        )
    )
    log(f"experience lane complete in {total_elapsed}s")
    return 0 if len(results) == TOTAL_TASKS else 1


if __name__ == "__main__":
    raise SystemExit(main())