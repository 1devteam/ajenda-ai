from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from backend.services.credentials.gmail_runtime_token import serialize_gmail_oauth_secret
from backend.services.tools.gmail_provider import required_gmail_scopes
from backend.services.tools.google_oauth_cli import (
    DEFAULT_GOOGLE_OAUTH_CONFIG_PATH,
    GoogleOAuthCliError,
    GoogleOAuthTokenBundle,
    load_google_oauth_config,
    resolve_gmail_access_token,
)


def resolve_gmail_access_token_for_e2e() -> str | None:
    """Prefer AJENDA_E2E_GMAIL_TOKEN when set; otherwise refresh ~/.ajenda/google-oauth.yml."""
    env_token = os.environ.get("AJENDA_E2E_GMAIL_TOKEN", "").strip()
    if env_token:
        return env_token
    return resolve_gmail_access_token(config_path=DEFAULT_GOOGLE_OAUTH_CONFIG_PATH)


def resolve_gmail_credential_secret_for_e2e() -> str | None:
    """Return Gmail OAuth JSON secret shape for Credentials API registration."""
    configured = os.environ.get("AJENDA_E2E_GMAIL_SECRET", "").strip()
    if configured:
        return configured

    if DEFAULT_GOOGLE_OAUTH_CONFIG_PATH.is_file():
        try:
            stored = load_google_oauth_config(DEFAULT_GOOGLE_OAUTH_CONFIG_PATH)
        except GoogleOAuthCliError:
            stored = None
        if isinstance(stored, dict) and isinstance(stored.get("access_token"), str):
            bundle = GoogleOAuthTokenBundle(
                access_token=str(stored["access_token"]).strip(),
                refresh_token=str(stored["refresh_token"]).strip()
                if isinstance(stored.get("refresh_token"), str)
                else None,
                expires_at=str(stored["expires_at"]).strip()
                if isinstance(stored.get("expires_at"), str)
                else (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
                scopes=tuple(str(item) for item in stored.get("scopes", []) if isinstance(item, str))
                or tuple(required_gmail_scopes()),
                token_type=str(stored.get("token_type") or "Bearer"),
            )
            return serialize_gmail_oauth_secret(bundle=bundle)

    token = resolve_gmail_access_token_for_e2e()
    if not token:
        return None
    return json.dumps(
        {
            "access_token": token,
            "expires_at": (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat(),
            "scopes": list(required_gmail_scopes()),
            "token_type": "Bearer",
        },
        sort_keys=True,
    )
