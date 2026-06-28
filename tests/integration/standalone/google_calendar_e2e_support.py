from __future__ import annotations

import json
import os
from pathlib import Path

from backend.services.tools.google_calendar_provider import GOOGLE_CALENDAR_READ_SCOPE

DEFAULT_GOOGLE_CALENDAR_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "google-calendar-oauth.json"
DEFAULT_GOOGLE_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "google-oauth.yml"


def _serialize_google_calendar_secret(payload: dict[str, object]) -> str:
    document = {
        "provider_kind": "google_calendar",
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_at": payload.get("expires_at"),
        "scopes": payload.get("scopes") or [GOOGLE_CALENDAR_READ_SCOPE],
        "token_type": payload.get("token_type"),
    }
    return json.dumps(document, sort_keys=True)


def _payload_has_calendar_scope(payload: dict[str, object]) -> bool:
    scopes = payload.get("scopes")
    if isinstance(scopes, list):
        return any(GOOGLE_CALENDAR_READ_SCOPE in str(item) for item in scopes)
    scope_raw = payload.get("scope")
    if isinstance(scope_raw, str):
        return GOOGLE_CALENDAR_READ_SCOPE in scope_raw
    return False


def resolve_google_calendar_credential_secret_for_e2e() -> str | None:
    configured = os.environ.get("AJENDA_E2E_GOOGLE_CALENDAR_SECRET", "").strip()
    if configured:
        return configured

    calendar_path = Path(
        os.environ.get("AJENDA_E2E_GOOGLE_CALENDAR_CONFIG_PATH", str(DEFAULT_GOOGLE_CALENDAR_OAUTH_CONFIG_PATH))
    )
    if calendar_path.is_file():
        text = calendar_path.read_text(encoding="utf-8").strip()
        if text:
            if text.startswith("{"):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    return text
                if isinstance(payload, dict):
                    if payload.get("provider_kind") == "google_calendar":
                        return text
                    if isinstance(payload.get("access_token"), str):
                        return _serialize_google_calendar_secret(payload)
            return text

    shared_path = Path(os.environ.get("AJENDA_E2E_GOOGLE_CONFIG_PATH", str(DEFAULT_GOOGLE_OAUTH_CONFIG_PATH)))
    if not shared_path.is_file():
        return None

    try:
        import yaml  # type: ignore[import-untyped]

        payload = yaml.safe_load(shared_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or not _payload_has_calendar_scope(payload):
        return None
    if not isinstance(payload.get("access_token"), str):
        return None
    return _serialize_google_calendar_secret(payload)