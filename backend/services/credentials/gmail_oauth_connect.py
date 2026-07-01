"""Product Gmail OAuth connect flow with signed state for Credentials API."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from backend.app.config import Settings, get_settings
from backend.services.credentials.gmail_runtime_token import serialize_gmail_oauth_secret
from backend.services.credentials.oauth_state import OAuthStateError, sign_oauth_state, verify_oauth_state
from backend.services.tools.google_oauth_cli import (
    GoogleOAuthCliError,
    build_google_authorization_url,
    exchange_authorization_code,
    resolve_google_oauth_client_config,
)

GMAIL_OAUTH_PROVIDER = "gmail"


class GmailOAuthConnectError(ValueError):
    """Deterministic Gmail OAuth connect failure."""


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
        client = type(client)(
            client_id=client.client_id,
            client_secret=client.client_secret,
            redirect_uri=redirect_uri,
        )
    except GoogleOAuthCliError as exc:
        raise GmailOAuthConnectError(str(exc)) from exc

    state = sign_oauth_state(
        {
            "tenant_id": tenant_id,
            "credential_id": credential_id.strip(),
            "actor_id": actor_id,
            "nonce": secrets.token_urlsafe(16),
            "issued_at": int(time.time()),
            "provider": GMAIL_OAUTH_PROVIDER,
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
    verify_gmail_oauth_state(state, settings=runtime_settings)
    redirect_uri = resolve_gmail_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_google_oauth_client_config()
        client = type(client)(
            client_id=client.client_id,
            client_secret=client.client_secret,
            redirect_uri=redirect_uri,
        )
        bundle = exchange_authorization_code(client=client, code=code.strip())
    except (GoogleOAuthCliError, OAuthStateError) as exc:
        raise GmailOAuthConnectError(str(exc)) from exc
    return serialize_gmail_oauth_secret(bundle=bundle)


def verify_gmail_oauth_state(state: str, *, settings: Settings | None = None):
    try:
        return verify_oauth_state(state, provider=GMAIL_OAUTH_PROVIDER, settings=settings)
    except OAuthStateError as exc:
        raise GmailOAuthConnectError(str(exc)) from exc