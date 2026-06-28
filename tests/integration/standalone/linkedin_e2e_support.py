from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_LINKEDIN_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "linkedin-oauth.json"


def resolve_linkedin_credential_secret_for_e2e() -> str | None:
    configured = os.environ.get("AJENDA_E2E_LINKEDIN_TOKEN", "").strip()
    if configured:
        return configured

    config_path = Path(
        os.environ.get("AJENDA_E2E_LINKEDIN_CONFIG_PATH", str(DEFAULT_LINKEDIN_OAUTH_CONFIG_PATH))
    )
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
        return text
    if isinstance(payload, dict) and isinstance(payload.get("access_token"), str):
        return json.dumps(payload, sort_keys=True)
    return text