from __future__ import annotations

from backend.services.tools.google_oauth_cli import DEFAULT_GOOGLE_OAUTH_CONFIG_PATH, resolve_gmail_access_token


def resolve_gmail_access_token_for_e2e() -> str | None:
    return resolve_gmail_access_token(config_path=DEFAULT_GOOGLE_OAUTH_CONFIG_PATH)
