#!/usr/bin/env python3
"""Report what is configured for brain missions M7/M8/M11 (LLM, email, charter)."""

from __future__ import annotations

import json
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
_load_frontend_env = _brain._load_frontend_env
_request = _brain._request
_auth_headers = _brain._auth_headers

SECRETS = Path.home() / ".ajenda" / "runtime-secrets.env"
COMPOSE_ENV = ROOT / "deploy/compose/.env.prod"


def _env_has_key(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key and value.strip() and value.strip() not in {"CHANGE_ME", '""', "''"}:
            return True
    return False


def main() -> int:
    tenant_id, api_key = _load_frontend_env()
    print("=== Ajenda brain readiness ===\n")

    llm_in_secrets = _env_has_key(SECRETS, "AJENDA_LLM_API_KEY")
    llm_in_compose = _env_has_key(COMPOSE_ENV, "AJENDA_LLM_API_KEY")
    email_in_secrets = _env_has_key(SECRETS, "AJENDA_EMAIL_PLATFORM_SMTP_SECRET")
    email_enabled = _env_has_key(SECRETS, "AJENDA_EMAIL_PLATFORM_MASTER_KEY_ENABLED") or _env_has_key(
        COMPOSE_ENV, "AJENDA_EMAIL_PLATFORM_MASTER_KEY_ENABLED"
    )

    print("Local config files:")
    print(f"  ~/.ajenda/runtime-secrets.env  {'present' if SECRETS.is_file() else 'MISSING'}")
    print(f"  AJENDA_LLM_API_KEY in secrets   {'yes' if llm_in_secrets else 'no'}")
    print(f"  AJENDA_LLM_API_KEY in compose    {'yes' if llm_in_compose else 'no'}")
    print(f"  Platform email SMTP secret      {'yes' if email_in_secrets else 'no'}")
    print(f"  Platform email enabled flag       {'yes' if email_enabled else 'no'}")
    print()

    if not tenant_id or not api_key:
        print("Dev tenant: MISSING — set AJENDA_DEV_TENANT_ID and AJENDA_DEV_API_KEY in ~/.ajenda/frontend.env")
        print("\nTo enable LLM:")
        print("  1. cp scripts/dev/runtime-secrets.env.example ~/.ajenda/runtime-secrets.env")
        print("  2. Set AJENDA_LLM_API_KEY=sk-...")
        print("  3. bash scripts/dev/sync-local-secrets.sh --recreate-api")
        return 2

    print(f"Dev tenant: {tenant_id}")
    try:
        report = _request(
            "GET",
            "/v1/ability-runtime/brain-capability-check",
            headers=_auth_headers(tenant_id, api_key),
        )
    except Exception as exc:
        print(f"API check failed: {exc}")
        return 1

    summary = report.get("summary", {})
    print(f"\nCapability: {json.dumps(summary)}")
    for mission in report.get("missions", []):
        if mission.get("mission_id") in {"M7", "M8", "M11"}:
            print(f"  {mission['mission_id']} {mission['status']:<12} {mission['note']}")

    if not llm_in_secrets and not llm_in_compose:
        print("\nNext: add AJENDA_LLM_API_KEY then run sync-local-secrets.sh --recreate-api")
    if summary.get("blocked"):
        print("\nBlocked missions detected — seed dogfood charter:")
        print("  python scripts/dev/brain-dogfood-gtm.py  # seeds charter on first step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())