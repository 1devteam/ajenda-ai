"""Signed OAuth state envelopes for provider credential connect flows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings, get_settings


class OAuthStateError(ValueError):
    """Deterministic OAuth state validation failure."""


@dataclass(frozen=True, slots=True)
class OAuthStateClaims:
    tenant_id: str
    credential_id: str
    actor_id: str
    nonce: str
    issued_at: int
    provider: str


def sign_oauth_state(payload: dict[str, Any], *, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")
    digest = hmac.new(_signing_key(runtime_settings), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{digest}"


def verify_oauth_state(state: str, *, provider: str, settings: Settings | None = None) -> OAuthStateClaims:
    runtime_settings = settings or get_settings()
    payload = _verify_state_body(state, settings=runtime_settings)
    for field in ("tenant_id", "credential_id", "actor_id", "nonce"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise OAuthStateError(f"oauth state missing {field}")
    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, int):
        raise OAuthStateError("oauth state missing issued_at")
    if payload.get("provider") != provider:
        raise OAuthStateError("oauth state provider mismatch")
    if int(time.time()) - issued_at > 600:
        raise OAuthStateError("oauth state expired")
    return OAuthStateClaims(
        tenant_id=payload["tenant_id"].strip(),
        credential_id=payload["credential_id"].strip(),
        actor_id=payload["actor_id"].strip(),
        nonce=payload["nonce"].strip(),
        issued_at=issued_at,
        provider=provider,
    )


def _signing_key(settings: Settings) -> bytes:
    secret = str(settings.session_signing_secret).strip()
    if not secret:
        secret = str(settings.runtime_secret_encryption_key or "").strip()
    if not secret:
        if settings.env in ("test", "development"):
            secret = "ajenda-test-oauth-state-signing-key"
        else:
            raise OAuthStateError("oauth state signing secret is not configured")
    return secret.encode("utf-8")


def _verify_state_body(state: str, *, settings: Settings) -> dict[str, Any]:
    if not state or "." not in state:
        raise OAuthStateError("oauth state is malformed")
    body, digest = state.rsplit(".", 1)
    expected = hmac.new(_signing_key(settings), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise OAuthStateError("oauth state signature mismatch")
    try:
        decoded = base64.urlsafe_b64decode(body.encode("ascii") + b"==")
        loaded = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthStateError("oauth state payload is invalid") from exc
    if not isinstance(loaded, dict):
        raise OAuthStateError("oauth state payload must be an object")
    return loaded
