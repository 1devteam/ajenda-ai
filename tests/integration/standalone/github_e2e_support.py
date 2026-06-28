from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_GITHUB_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "github-oauth.json"


def resolve_github_credential_secret_for_e2e() -> str | None:
    configured = os.environ.get("AJENDA_E2E_GITHUB_SECRET", "").strip() or os.environ.get(
        "AJENDA_E2E_GITHUB_TOKEN", ""
    ).strip()
    if configured:
        return configured

    config_path = Path(os.environ.get("AJENDA_E2E_GITHUB_CONFIG_PATH", str(DEFAULT_GITHUB_OAUTH_CONFIG_PATH)))
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
        if payload.get("provider_kind") == "github":
            return json.dumps(payload, sort_keys=True)
        return json.dumps(
            {
                "provider_kind": "github",
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "expires_at": payload.get("expires_at"),
                "scopes": payload.get("scopes") or [],
                "token_type": payload.get("token_type"),
            },
            sort_keys=True,
        )
    return text