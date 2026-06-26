from __future__ import annotations

import os
from pathlib import Path

import yaml


def resolve_hubspot_access_token() -> str | None:
    explicit = os.environ.get("AJENDA_E2E_HUBSPOT_PAK", "").strip()
    if explicit:
        return explicit

    config_path = Path.home() / ".hscli" / "config.yml"
    if not config_path.is_file():
        return None
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    accounts = config.get("accounts")
    if not isinstance(accounts, list):
        return None
    for account in accounts:
        if not isinstance(account, dict):
            continue
        auth = account.get("auth")
        if not isinstance(auth, dict):
            continue
        token_info = auth.get("tokenInfo")
        if not isinstance(token_info, dict):
            continue
        token = token_info.get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()
        personal_access_key = account.get("personalAccessKey")
        if isinstance(personal_access_key, str) and personal_access_key.strip():
            return personal_access_key.strip()
    return None
