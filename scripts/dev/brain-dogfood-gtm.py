#!/usr/bin/env python3
"""Run the M11 dogfood GTM pipeline against the local dev stack.

Sequence: seed charter → research → draft → approve → (optional) send → CRM upsert.

Uses dev tenant credentials from ~/.ajenda/frontend.env. Real SMTP send only when
AJENDA_BRAIN_DOGFOOD_SEND=1 (or AJENDA_BRAIN_CAPSTONE_SEND=1) and platform email is configured.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

_brain_mod_path = ROOT / "scripts/dev/brain-10-missions.py"
_brain_spec = importlib.util.spec_from_file_location("brain_missions", _brain_mod_path)
assert _brain_spec and _brain_spec.loader
_brain = importlib.util.module_from_spec(_brain_spec)
_brain_spec.loader.exec_module(_brain)
_assess = _brain._assess
_auth_headers = _brain._auth_headers
_load_frontend_env = _brain._load_frontend_env
_request = _brain._request
_run_mission_sync = _brain._run_mission_sync
_seed_demo_profile = _brain._seed_demo_profile
_seed_dogfood_charter = _brain._seed_dogfood_charter

PROSPECT_EMAIL = "ops@northwind-logistics.example"
PROSPECT_DOMAIN = "northwind-logistics.example"
PROSPECT_COMPANY = "Northwind Logistics"


def _send_enabled() -> bool:
    return os.environ.get("AJENDA_BRAIN_DOGFOOD_SEND") == "1" or os.environ.get("AJENDA_BRAIN_CAPSTONE_SEND") == "1"


def _step(label: str, spec: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    print(f"[dogfood] {label} …", flush=True)
    result = _run_mission_sync(spec["tenant_id"], spec["mission"])
    status, note = _assess(spec["mission"], result)
    print(f"[dogfood]   {status}: {note}")
    return result, status, note


def main() -> int:
    tenant_id, api_key = _load_frontend_env()
    if not tenant_id or not api_key:
        print("ERROR: set AJENDA_DEV_TENANT_ID and AJENDA_DEV_API_KEY", file=sys.stderr)
        return 2

    headers = _auth_headers(tenant_id, api_key)
    print(f"[dogfood] tenant={tenant_id}")

    try:
        _seed_demo_profile(tenant_id, api_key)
        _seed_dogfood_charter(tenant_id, api_key)
        print("[dogfood] business profile + dogfood charter seeded")
    except Exception as exc:
        print(f"[dogfood] WARN: seed skipped: {exc}", file=sys.stderr)

    steps: list[dict[str, str]] = []
    artifact_id: str | None = None
    send_result: dict[str, Any] = {}

    research_spec = {
        "mission": "Dogfood step 1 — research",
        "outcome": "brain-first prospect research",
        "action": "sales.research",
        "tier": "prepare/read",
        "side_effect_class": "none",
        "input": {"lead": {"company": PROSPECT_COMPANY, "domain": PROSPECT_DOMAIN}},
    }
    _, research_status, research_note = _step(
        "research",
        {"tenant_id": tenant_id, "mission": research_spec},
    )
    steps.append({"step": "research", "status": research_status, "note": research_note})

    draft_spec = {
        "mission": "Dogfood step 2 — draft",
        "outcome": "pitch_email artifact",
        "action": "gtm.email_draft",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {
            "recipient": PROSPECT_EMAIL,
            "topic": "Ajenda clerical worker pilot",
            "tone": "professional",
            "context": {"dogfood": True, "company": PROSPECT_COMPANY},
        },
    }
    draft_result, draft_status, draft_note = _step(
        "draft",
        {"tenant_id": tenant_id, "mission": draft_spec},
    )
    steps.append({"step": "draft", "status": draft_status, "note": draft_note})
    artifact_id = (draft_result.get("output") or {}).get("artifact_id")
    if not artifact_id:
        print("[dogfood] FAIL: draft did not persist artifact_id", file=sys.stderr)
        return 1

    print(f"[dogfood] artifact_id={artifact_id}")
    approved = _request(
        "POST",
        f"/v1/review-queue/{artifact_id}/approve",
        body={"note": "dogfood GTM proof"},
        headers=headers,
    )
    approve_status = str(approved.get("review_status") or "")
    print(f"[dogfood] approve review_status={approve_status}")
    steps.append(
        {
            "step": "approve",
            "status": "PASS" if approve_status == "approved" else "FAIL",
            "note": approve_status,
        }
    )
    if approve_status != "approved":
        return 1

    if _send_enabled():
        send_spec = {
            "mission": "Dogfood step 4 — send",
            "outcome": "artifact-gated send",
            "action": "gtm.email_send",
            "tier": "perform",
            "side_effect_class": "external_send",
            "input": {"to": PROSPECT_EMAIL, "artifact_id": artifact_id},
        }
        send_result, send_status, send_note = _step(
            "send",
            {"tenant_id": tenant_id, "mission": send_spec},
        )
        steps.append({"step": "send", "status": send_status, "note": send_note})
        if send_status == "FAIL":
            return 1
    else:
        print("[dogfood] send skipped (set AJENDA_BRAIN_DOGFOOD_SEND=1 to exercise SMTP)")
        steps.append({"step": "send", "status": "SKIP", "note": "AJENDA_BRAIN_DOGFOOD_SEND not set"})

    crm_spec = {
        "mission": "Dogfood step 5 — CRM",
        "outcome": "log outreach in pipeline",
        "action": "gtm.crm_upsert",
        "tier": "perform (internal)",
        "side_effect_class": "internal_write",
        "input": {
            "record_type": "contact",
            "data": {
                "email": "jordan.lee@northwind-logistics.example",
                "firstname": "Jordan",
                "lastname": "Lee",
                "company": PROSPECT_COMPANY,
                "notes": f"Dogfood outreach artifact={artifact_id}",
            },
        },
    }
    crm_result, crm_status, crm_note = _step(
        "crm_upsert",
        {"tenant_id": tenant_id, "mission": crm_spec},
    )
    steps.append({"step": "crm_upsert", "status": crm_status, "note": crm_note})

    capability = _request("GET", "/v1/ability-runtime/brain-capability-check", headers=headers)
    m11 = next((item for item in capability.get("missions", []) if item.get("mission_id") == "M11"), None)
    print(f"[dogfood] M11 readiness: {json.dumps(m11, indent=2) if m11 else 'missing'}")

    print("\n=== Dogfood GTM evidence summary ===")
    for row in steps:
        print(f"  {row['step']:<12} {row['status']:<8} {row['note']}")

    failed = sum(1 for row in steps if row["status"] == "FAIL")
    if failed:
        return 1

    crm_output = crm_result.get("output") or {}
    send_real = (send_result.get("output") or {}).get("real") if _send_enabled() else "skipped"
    print(f"\n[dogfood] PASS — artifact={artifact_id}, crm_id={crm_output.get('id')}, send_real={send_real}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())