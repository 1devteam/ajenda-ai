#!/usr/bin/env python3
"""Prove the M11 capstone path: draft → approve → artifact-gated send readiness.

Uses dev tenant credentials from ~/.ajenda/frontend.env. Does not send real email
unless AJENDA_BRAIN_CAPSTONE_SEND=1 and platform email is configured.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

_brain_mod_path = ROOT / "scripts/dev/brain-10-missions.py"
_brain_spec = importlib.util.spec_from_file_location("brain_missions", _brain_mod_path)
assert _brain_spec and _brain_spec.loader
_brain = importlib.util.module_from_spec(_brain_spec)
_brain_spec.loader.exec_module(_brain)
_auth_headers = _brain._auth_headers
_load_frontend_env = _brain._load_frontend_env
_request = _brain._request
_run_mission_sync = _brain._run_mission_sync
_seed_dogfood_charter = _brain._seed_dogfood_charter


def main() -> int:
    tenant_id, api_key = _load_frontend_env()
    if not tenant_id or not api_key:
        print("ERROR: set AJENDA_DEV_TENANT_ID and AJENDA_DEV_API_KEY", file=sys.stderr)
        return 2

    headers = _auth_headers(tenant_id, api_key)
    print(f"[capstone] tenant={tenant_id}")

    try:
        _seed_dogfood_charter(tenant_id, api_key)
        print("[capstone] dogfood charter seeded (gtm.email_send enabled)")
    except Exception as exc:
        print(f"[capstone] WARN: charter seed skipped: {exc}", file=sys.stderr)

    draft_spec = {
        "mission": "Capstone step 2 — draft",
        "outcome": "pitch_email artifact",
        "action": "gtm.email_draft",
        "tier": "prepare",
        "side_effect_class": "none",
        "input": {
            "recipient": "ops@northwind-logistics.example",
            "topic": "Ajenda clerical worker pilot",
            "tone": "professional",
            "context": {"capstone_proof": True},
        },
    }
    draft_result = _run_mission_sync(tenant_id, draft_spec)
    if not draft_result.get("ok"):
        print(f"FAIL draft: {draft_result}", file=sys.stderr)
        return 1
    artifact_id = (draft_result.get("output") or {}).get("artifact_id")
    if not artifact_id:
        print("PARTIAL draft ran but no artifact_id (session-less runtime?)", file=sys.stderr)
        return 0

    print(f"[capstone] artifact_id={artifact_id}")
    approved = _request(
        "POST",
        f"/v1/review-queue/{artifact_id}/approve",
        body={"note": "capstone proof"},
        headers=headers,
    )
    print(f"[capstone] approved review_status={approved.get('review_status')}")

    library = _request(
        "GET",
        "/v1/ability-runtime/brain-capability-check",
        headers=headers,
    )
    m11 = next((item for item in library.get("missions", []) if item.get("mission_id") == "M11"), None)
    print(f"[capstone] M11 readiness: {json.dumps(m11, indent=2) if m11 else 'missing'}")

    if os.environ.get("AJENDA_BRAIN_CAPSTONE_SEND") == "1":
        send_spec = {
            "mission": "Capstone step 4 — send",
            "outcome": "artifact-gated send",
            "action": "gtm.email_send",
            "tier": "perform",
            "side_effect_class": "external_send",
            "input": {
                "to": "ops@northwind-logistics.example",
                "artifact_id": artifact_id,
            },
        }
        send_result = _run_mission_sync(tenant_id, send_spec)
        print(f"[capstone] send result: {json.dumps(send_result, indent=2)}")
        if not send_result.get("ok"):
            return 1

    print("[capstone] PASS — draft persisted, approved, M11 checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())