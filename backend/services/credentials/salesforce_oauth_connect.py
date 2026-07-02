"""Product Salesforce OAuth connect flow with signed state for Credentials API."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from backend.app.config import Settings, get_settings
from backend.services.credentials.oauth_state import (
    OAuthStateClaims,
    OAuthStateError,
    sign_oauth_state,
    verify_oauth_state,
)
from backend.services.credentials.salesforce_oauth_client import (
    SalesforceOAuthError,
    build_salesforce_authorization_url,
    exchange_salesforce_authorization_code,
    instance_host_from_url,
    resolve_salesforce_oauth_client_config,
)
from backend.services.credentials.salesforce_runtime_token import serialize_salesforce_oauth_secret

SALESFORCE_OAUTH_PROVIDER = "salesforce"


class SalesforceOAuthConnectError(ValueError):
    """Deterministic Salesforce OAuth connect failure."""


@dataclass(frozen=True, slots=True)
class SalesforceOAuthAuthorizeResult:
    authorization_url: str
    state: str
    redirect_uri: str


@dataclass(frozen=True, slots=True)
class SalesforceOAuthConnectSecret:
    secret_value: str
    trusted_destination_hosts: tuple[str, ...]


def resolve_salesforce_product_redirect_uri(*, settings: Settings | None = None) -> str:
    runtime_settings = settings or get_settings()
    configured = str(getattr(runtime_settings, "salesforce_oauth_redirect_uri", "")).strip()
    if configured:
        return configured
    return "http://localhost:5173/credentials/salesforce/callback"


def issue_salesforce_oauth_authorization(
    *,
    tenant_id: str,
    credential_id: str,
    actor_id: str,
    settings: Settings | None = None,
) -> SalesforceOAuthAuthorizeResult:
    runtime_settings = settings or get_settings()
    redirect_uri = resolve_salesforce_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_salesforce_oauth_client_config(redirect_uri=redirect_uri)
    except SalesforceOAuthError as exc:
        raise SalesforceOAuthConnectError(str(exc)) from exc

    state = sign_oauth_state(
        {
            "tenant_id": tenant_id,
            "credential_id": credential_id.strip(),
            "actor_id": actor_id,
            "nonce": secrets.token_urlsafe(16),
            "issued_at": int(time.time()),
            "provider": SALESFORCE_OAUTH_PROVIDER,
        },
        settings=runtime_settings,
    )
    return SalesforceOAuthAuthorizeResult(
        authorization_url=build_salesforce_authorization_url(client=client, state=state),
        state=state,
        redirect_uri=redirect_uri,
    )


def exchange_salesforce_oauth_code(
    *, code: str, state: str, settings: Settings | None = None
) -> SalesforceOAuthConnectSecret:
    runtime_settings = settings or get_settings()
    verify_salesforce_oauth_state(state, settings=runtime_settings)
    redirect_uri = resolve_salesforce_product_redirect_uri(settings=runtime_settings)
    try:
        client = resolve_salesforce_oauth_client_config(redirect_uri=redirect_uri)
        bundle = exchange_salesforce_authorization_code(client=client, code=code)
    except (SalesforceOAuthError, OAuthStateError) as exc:
        raise SalesforceOAuthConnectError(str(exc)) from exc
    host = instance_host_from_url(bundle.instance_url)
    return SalesforceOAuthConnectSecret(
        secret_value=serialize_salesforce_oauth_secret(bundle=bundle),
        trusted_destination_hosts=(host,),
    )


def verify_salesforce_oauth_state(state: str, *, settings: Settings | None = None) -> OAuthStateClaims:
    try:
        return verify_oauth_state(state, provider=SALESFORCE_OAUTH_PROVIDER, settings=settings)
    except OAuthStateError as exc:
        raise SalesforceOAuthConnectError(str(exc)) from exc
