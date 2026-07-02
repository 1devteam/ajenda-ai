from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "salesforce-oauth.json"


def resolve_salesforce_credential_secret_for_e2e() -> str | None:
    configured = os.environ.get("AJENDA_E2E_SALESFORCE_SECRET", "").strip()
    if configured:
        return configured

    token = os.environ.get("AJENDA_E2E_SALESFORCE_TOKEN", "").strip()
    instance_host = os.environ.get("AJENDA_E2E_SALESFORCE_INSTANCE_HOST", "").strip().lower().rstrip(".")
    if token and instance_host:
        return json.dumps(
            {
                "provider_kind": "salesforce",
                "access_token": token,
                "instance_url": f"https://{instance_host}",
            },
            sort_keys=True,
        )

    config_path = Path(os.environ.get("AJENDA_E2E_SALESFORCE_CONFIG_PATH", str(DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH)))
    if not config_path.is_file():
        return None

    text = config_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if text.startswith("{"):
        return text

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("access_token"), str) and isinstance(payload.get("instance_url"), str):
        return json.dumps(payload, sort_keys=True)
    return None
