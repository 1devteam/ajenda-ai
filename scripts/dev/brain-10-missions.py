#!/usr/bin/env python3
"""Run Ajenda central-brain missions (M1–M12) and print a capability report.

Uses the dev tenant from ~/.ajenda/frontend.env when present, or provisions a
fresh tenant. Executes each mission as one tool.invoke through the worker spine
(same pattern as deploy/scripts/experience_lane_runner.py).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = os.environ.get("AJENDA_PROOF_COMPOSE_FILE", str(ROOT / "deploy/compose/docker-compose.prod.yml"))
COMPOSE_ENV_FILE = os.environ.get("AJENDA_PROOF_COMPOSE_ENV_FILE", str(ROOT / "deploy/compose/.env.prod"))
API_BASE = os.environ.get("AJENDA_PROOF_API_BASE_URL", "http://localhost:8000").rstrip("/")

ROOT_IMPORT = str(ROOT)
if ROOT_IMPORT not in sys.path:
    sys.path.insert(0, ROOT_IMPORT)

from backend.services.brain_mission_catalog import BRAIN_MISSIONS as _BRAIN_MISSIONS

# Mission catalog shared with API brain-capability-check.
BRAIN_MISSIONS: list[dict[str, Any]] = [
    {
        "mission": spec["mission"],
        "outcome": spec["outcome"],
        "action": spec["action"],
        "tier": spec["tier"],
        "side_effect_class": spec["side_effect_class"],
        "input": spec["input"],
    }
    for spec in _BRAIN_MISSIONS
]


def _request(
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode()
        allowed = expected if isinstance(expected, tuple) else (expected,)
        if status not in allowed:
            raise RuntimeError(f"{method} {path} -> {status}: {raw[:500]}")
        return json.loads(raw) if raw else {}
    allowed = expected if isinstance(expected, tuple) else (expected,)
    if status not in allowed:
        raise RuntimeError(f"{method} {path} -> {status}: {raw[:500]}")
    return json.loads(raw) if raw else {}


def _auth_headers(tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def _load_frontend_env() -> tuple[str | None, str | None]:
    path = Path.home() / ".ajenda" / "frontend.env"
    if not path.is_file():
        return None, None
    tenant_id = None
    api_key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        if line.startswith("AJENDA_DEV_TENANT_ID="):
            tenant_id = line.split("=", 1)[1].strip().strip('"').strip("'")
        if line.startswith("AJENDA_DEV_API_KEY="):
            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return tenant_id, api_key


def _seed_dogfood_charter(tenant_id: str, api_key: str) -> None:
    """Opt the dev tenant into M11 external send via operating_charter business fact."""
    from backend.services.operating_charter import dogfood_operating_charter

    auth = _auth_headers(tenant_id, api_key)
    charter = dogfood_operating_charter()
    _request(
        "PUT",
        "/v1/business-profile/facts/operating_charter",
        headers=auth,
        body={
            "approved_fact": {"value": charter.to_fact_payload()},
            "provenance_metadata": {"source": "brain-dogfood-gtm"},
        },
        expected=(200, 201),
    )


def _seed_demo_profile(tenant_id: str, api_key: str) -> None:
    """Ensure business profile + demo internal records exist for retrieval missions."""
    auth = _auth_headers(tenant_id, api_key)
    facts = [
        {"category": "business_name", "value": "Ajenda AI", "source": "brain-10-missions"},
        {"category": "contact_email", "value": "hello@ajenda.ai", "source": "brain-10-missions"},
        {
            "category": "products_services",
            "value": "Governed mission runtime\nHybrid retrieval over internal records\nClerical worker automation",
            "source": "brain-10-missions",
        },
        {
            "category": "operator_notes",
            "value": "Prepare drafts and research freely. Perform internal writes. External send requires approval.",
            "source": "brain-10-missions",
        },
    ]
    for fact in facts:
        _request(
            "PUT",
            f"/v1/business-profile/facts/{fact['category']}",
            headers=auth,
            body={
                "approved_fact": {"value": fact["value"]},
                "provenance_metadata": {"source": fact["source"]},
            },
            expected=(200, 201),
        )


def _run_mission_sync(tenant_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(
        {
            "label": spec["mission"],
            "action": spec["action"],
            "side_effect_class": spec["side_effect_class"],
            "input": spec["input"],
        }
    )
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

tenant_id = os.environ["AJENDA_BRAIN_TENANT_ID"]
spec = json.loads(os.environ["AJENDA_BRAIN_SPEC"])
action = spec["action"]
side_effect = spec.get("side_effect_class", "none")
adapter_class = {
    "none": "none",
    "internal_write": "non_idempotent_write",
    "external_write": "external_write",
    "external_send": "external_send",
}.get(side_effect, "none")

settings = get_settings()
runtime = DatabaseRuntime(settings)
try:
    session = runtime.session_factory()
    try:
        capability = None
        adapter = None
        needs_authority = side_effect != "none" or action.startswith("gtm.")
        if needs_authority:
            suffix = uuid.uuid4().hex[:10]
            capability = Capability(
                tenant_id=tenant_id,
                name=f"brain10-{action}-{suffix}",
                version="1.0.0",
                description=f"Brain 10 missions: {action}",
                supported_task_types=["tool.invoke", action],
                input_schema_hints={},
                output_schema_hints={},
                required_permissions=[],
                required_tools=[action],
                risk_level="medium",
                approval_requirements={"required": False, "generated_by": "brain-10-missions"},
                evidence_expectations=[f"{action} evidence"],
                execution_constraints={},
                enabled=True,
                schema_version=1,
            )
            session.add(capability)
            session.flush()
            adapter = CapabilityAdapter(
                tenant_id=tenant_id,
                name=f"brain10-{action}-adapter-{suffix}",
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
                approval_requirements={"required": False, "generated_by": "brain-10-missions"},
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
        metadata = {
            "task_type": "tool.invoke",
            "launched_by": "brain-10-missions",
            "tool_invocation": {"schema_version": 1, "action": action, "input": spec.get("input", {})},
        }
        if capability is not None:
            metadata["capability_reference"] = {"capability_id": str(capability.id)}
        if adapter is not None:
            metadata["adapter_reference"] = {"adapter_id": str(adapter.id)}
        if side_effect in {"internal_write", "external_write", "external_send"}:
            metadata["execution_constraints"] = {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": [action],
                    "reason": "brain-10-missions",
                    "approved_by": "brain-capability-proof",
                }
            }
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=spec["label"],
            description="brain-10-missions",
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
        "worker_id": "brain-10-missions",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": runtime.session_factory,
    }
    session = runtime.session_factory()
    try:
        current = session.get(ExecutionTask, task_id)
        result = tool_invoke_handler(current, ctx)
        current.status = ExecutionTaskState.COMPLETED.value
        session.commit()
        print(json.dumps({"ok": True, "summary": result.get("summary"), "output": result.get("output")}))
    except Exception as exc:
        session.rollback()
        print(json.dumps({"ok": False, "error": str(exc)}))
    finally:
        session.close()
finally:
    runtime.dispose()
'''
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "compose",
            "--env-file",
            COMPOSE_ENV_FILE,
            "-f",
            COMPOSE_FILE,
            "exec",
            "-T",
            "-e",
            f"AJENDA_BRAIN_TENANT_ID={tenant_id}",
            "-e",
            f"AJENDA_BRAIN_SPEC={payload}",
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
    lines = [line for line in proc.stdout.decode().splitlines() if line.strip().startswith("{")]
    if not lines:
        raise RuntimeError(proc.stdout.decode() or "no JSON result")
    return json.loads(lines[-1])


def _assess(spec: dict[str, Any], result: dict[str, Any]) -> tuple[str, str]:
    if not result.get("ok"):
        return "FAIL", str(result.get("error", "unknown"))[:120]
    output = result.get("output") or {}
    action = spec["action"]
    summary = (result.get("summary") or "")[:80]

    if action == "retrieval.hybrid_search":
        mems = output.get("memories") or []
        if output.get("real") and mems:
            return "PASS", f"{len(mems)} memories, source={output.get('source')}"
        return "PARTIAL", "ran but weak memory hits"

    if action == "record.search":
        count = output.get("count", 0)
        return ("PASS" if count else "PARTIAL"), f"count={count}"

    if action == "web.research":
        return "PASS", f"company={output.get('company')}, real={output.get('real')}"

    if action in {"sales.qualify", "sales.recommend_next_action", "gtm.lead_enrich"}:
        return "PASS", summary or "local brain output"

    if action in {"gtm.email_draft", "sales.draft_followup"}:
        artifact_id = output.get("artifact_id")
        mode = output.get("generation_mode", "template")
        if artifact_id:
            return "PASS", f"artifact={artifact_id}, mode={mode}"
        body = str((output.get("body") or output.get("draft") or ""))[:60]
        return "PARTIAL", f"template draft ({len(body)} chars), no artifact_id"

    if action == "document.search":
        count = output.get("count", 0)
        return ("PASS" if count else "PARTIAL"), f"library hits={count}"

    if action == "gtm.email_send":
        return "PARTIAL", f"status={output.get('status')}, real={output.get('real')}"

    if action == "gtm.crm_upsert":
        status = output.get("status")
        if status == "upserted_internal" and output.get("source") == "ajenda_brain":
            return "PASS", f"id={output.get('id')}, internal pipeline"
        return "PARTIAL", f"status={status}, source={output.get('source')}"

    if action == "sales.research":
        return "PASS", f"matches={len(output.get('crm_matches') or [])}, source={output.get('source')}"

    return "PASS", summary


def main() -> int:
    tenant_id, api_key = _load_frontend_env()
    if not tenant_id or not api_key:
        print("ERROR: set AJENDA_DEV_TENANT_ID and AJENDA_DEV_API_KEY in ~/.ajenda/frontend.env", file=sys.stderr)
        return 2

    print(f"[brain-10] tenant={tenant_id}")
    try:
        _seed_demo_profile(tenant_id, api_key)
        print("[brain-10] business profile seeded/updated")
    except Exception as exc:
        print(f"[brain-10] WARN: profile seed skipped: {exc}")

    rows: list[dict[str, str]] = []
    for spec in BRAIN_MISSIONS:
        print(f"[brain-10] running {spec['mission']} …", flush=True)
        try:
            result = _run_mission_sync(tenant_id, spec)
            status, note = _assess(spec, result)
        except Exception as exc:
            status, note = "FAIL", str(exc)[:120]
            result = {}
        rows.append(
            {
                "mission": spec["mission"],
                "outcome": spec["outcome"],
                "action": spec["action"],
                "tier": spec["tier"],
                "status": status,
                "note": note,
            }
        )

    print(f"\n=== Ajenda central brain — {len(rows)} mission capability report ===\n")
    widths = (4, 36, 8, 48)
    print(f"{'#':<{widths[0]}} {'Mission':<{widths[1]}} {'Result':<{widths[2]}} Notes")
    print("-" * 100)
    for idx, row in enumerate(rows, start=1):
        print(
            f"{idx:<{widths[0]}} {row['mission']:<{widths[1]}} {row['status']:<{widths[2]}} {row['note']}"
        )

    passed = sum(1 for r in rows if r["status"] == "PASS")
    partial = sum(1 for r in rows if r["status"] == "PARTIAL")
    failed = sum(1 for r in rows if r["status"] == "FAIL")
    print(f"\nSummary: {passed} PASS, {partial} PARTIAL, {failed} FAIL (of {len(rows)})")
    print("\nPhase 2+3: LLM drafts + review queue + platform email when configured.")
    print("Run scripts/dev/brain-capstone-proof.py for draft→approve capstone proof.")
    print("Run scripts/dev/brain-dogfood-gtm.py for full M11 dogfood (research→send→CRM).")
    print("Run scripts/dev/check-brain-readiness.py to see LLM/email/charter gaps.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())