"""Product Gmail OAuth connect flow with signed state for Credentials API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from backend.app.config import Settings, get_settings
from backend.services.credentials.gmail_runtime_token import serialize_gmail_oauth_secret
from backend.services.tools.google_oauth_cli import (
    GoogleOAuthCliError,
    build_google_authorization_url,
    exchange_authorization_code,
    resolve_google_oauth_client_config,
)


class GmailOAuthConnectError(ValueError):
    """Deterministic Gmail OAuth connect failure."""


@dataclass(frozen=True, slots=True)
class GmailOAuthStateClaims:
    tenant_id: str
    credential_id: str
    actor_id: str
    nonce: str
    issued_at: int


@dataclass(frozen=True, slots=True)
class GmailOAuthAuthorizeResult:
    authorization_url: str
    state: str
    redirect_uri: str


def resolve_gmail_product_redirect_uri(*, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    configured = str(getattr(runtime_settings, "gmail_oauth_redirect_uri", "")).strip()
    if configured:
        return configured
    return "http://localhost:5173/credentials/gmail/callback"


def issue_gmail_oauth_authorization(
    *,
    tenant_id: str,
    credential_id: str,
    actor_id: str,
    settings: Settings | None = None,
) -> GmailOAuthAuthorizeResult:
    runtime_settings = settings or get_settings()
    redirect_uri = resolve_gmail_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_google_oauth_client_config()
    except GoogleOAuthCliError as exc:
        raise GmailOAuthConnectError(str(exc)) from exc

    client = type(client)(
        client_id=client.client_id,
        client_secret=client.client_secret,
        redirect_uri=redirect_uri,
    )
    state = _sign_state(
        {
            "tenant_id": tenant_id,
            "credential_id": credential_id.strip(),
            "actor_id": actor_id,
            "nonce": secrets.token_urlsafe(16),
            "issued_at": int(time.time()),
        },
        settings=runtime_settings,
    )
    return GmailOAuthAuthorizeResult(
        authorization_url=build_google_authorization_url(client=client, state=state),
        state=state,
        redirect_uri=redirect_uri,
    )


def exchange_gmail_oauth_code(*, code: str, state: str, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    claims = verify_gmail_oauth_state(state, settings=runtime_settings)
    redirect_uri = resolve_gmail_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_google_oauth_client_config()
    except GoogleOAuthCliError as exc:
        raise GmailOAuthConnectError(str(exc)) from exc

    client = type(client)(
        client_id=client.client_id,
        client_secret=client.client_secret,
        redirect_uri=redirect_uri,
    )
    try:
        bundle = exchange_authorization_code(client=client, code=code.strip())
    except GoogleOAuthCliError as exc:
        raise GmailOAuthConnectError(f"Gmail OAuth code exchange failed: {exc}") from exc

    _ = claims
    return serialize_gmail_oauth_secret(bundle=bundle)


def verify_gmail_oauth_state(state: str, *, settings: Settings | None = None) -> GmailOAuthStateClaims:
    payload = _verify_state(state, settings=settings or get_settings())
    for field in ("tenant_id", "credential_id", "actor_id", "nonce"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GmailOAuthConnectError(f"oauth state missing {field}")
    issued_at = payload.get("issued_at")
    if not isinstance(issued_at, int):
        raise GmailOAuthConnectError("oauth state missing issued_at")
    ttl_seconds = 600
    if int(time.time()) - issued_at > ttl_seconds:
        raise GmailOAuthConnectError("oauth state expired")
    return GmailOAuthStateClaims(
        tenant_id=payload["tenant_id"].strip(),
        credential_id=payload["credential_id"].strip(),
        actor_id=payload["actor_id"].strip(),
        nonce=payload["nonce"].strip(),
        issued_at=issued_at,
    )


def _signing_key(settings: Settings) -> bytes:
    secret = str(settings.session_signing_secret).strip()
    if not secret:
        secret = str(settings.runtime_secret_encryption_key or "").strip()
    if not secret:
        secret = "ajenda-test-gmail-oauth-state-signing-key"
    return secret.encode("utf-8")


def _sign_state(payload: dict[str, Any], *, settings: Settings) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode("utf-8")).decode("ascii")
    digest = hmac.new(_signing_key(settings), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{digest}"


def _verify_state(state: str, *, settings: Settings) -> dict[str, Any]:
    if not state or "." not in state:
        raise GmailOAuthConnectError("oauth state is malformed")
    body, digest = state.rsplit(".", 1)
    expected = hmac.new(_signing_key(settings), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        raise GmailOAuthConnectError("oauth state signature mismatch")
    try:
        decoded = base64.urlsafe_b64decode(body.encode("ascii") + b"==")
        loaded = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise GmailOAuthConnectError("oauth state payload is invalid") from exc
    if not isinstance(loaded, dict):
        raise GmailOAuthConnectError("oauth state payload must be an object")
    return loaded