"""Product LinkedIn OAuth connect flow with signed state for Credentials API."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from backend.app.config import Settings, get_settings
from backend.services.credentials.linkedin_oauth_client import (
    LinkedInOAuthClientError,
    build_linkedin_authorization_url,
    exchange_linkedin_authorization_code,
    resolve_linkedin_oauth_client_config,
)
from backend.services.credentials.linkedin_runtime_token import serialize_linkedin_oauth_secret
from backend.services.credentials.oauth_state import OAuthStateError, sign_oauth_state, verify_oauth_state

LINKEDIN_OAUTH_PROVIDER = "linkedin"


class LinkedInOAuthConnectError(ValueError):
    """Deterministic LinkedIn OAuth connect failure."""


@dataclass(frozen=True, slots=True)
class LinkedInOAuthAuthorizeResult:
    authorization_url: str
    state: str
    redirect_uri: str


def resolve_linkedin_product_redirect_uri(*, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    configured = str(getattr(runtime_settings, "linkedin_oauth_redirect_uri", "")).strip()
    if configured:
        return configured
    return "http://localhost:5173/credentials/linkedin/callback"


def issue_linkedin_oauth_authorization(
    *,
    tenant_id: str,
    credential_id: str,
    actor_id: str,
    settings: Settings | None = None,
) -> LinkedInOAuthAuthorizeResult:
    runtime_settings = settings or get_settings()
    redirect_uri = resolve_linkedin_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_linkedin_oauth_client_config(redirect_uri=redirect_uri)
    except LinkedInOAuthClientError as exc:
        raise LinkedInOAuthConnectError(str(exc)) from exc

    state = sign_oauth_state(
        {
            "tenant_id": tenant_id,
            "credential_id": credential_id.strip(),
            "actor_id": actor_id,
            "nonce": secrets.token_urlsafe(16),
            "issued_at": int(time.time()),
            "provider": LINKEDIN_OAUTH_PROVIDER,
        },
        settings=runtime_settings,
    )
    return LinkedInOAuthAuthorizeResult(
        authorization_url=build_linkedin_authorization_url(client=client, state=state),
        state=state,
        redirect_uri=redirect_uri,
    )


def exchange_linkedin_oauth_code(*, code: str, state: str, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    verify_linkedin_oauth_state(state, settings=runtime_settings)
    redirect_uri = resolve_linkedin_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_linkedin_oauth_client_config(redirect_uri=redirect_uri)
        bundle = exchange_linkedin_authorization_code(client=client, code=code)
    except LinkedInOAuthClientError as exc:
        raise LinkedInOAuthConnectError(str(exc)) from exc
    return serialize_linkedin_oauth_secret(bundle=bundle)


def verify_linkedin_oauth_state(state: str, *, settings: Settings | None = None):
    try:
        return verify_oauth_state(state, provider=LINKEDIN_OAUTH_PROVIDER, settings=settings)
    except OAuthStateError as exc:
        raise LinkedInOAuthConnectError(str(exc)) from exc
