"""Salesforce OAuth client for product credential connect and runtime refresh."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

DEFAULT_SALESFORCE_LOGIN_URL = "https://login.salesforce.com"
DEFAULT_SALESFORCE_OAUTH_SCOPES = ("api", "refresh_token")


class SalesforceOAuthError(ValueError):
    """Deterministic Salesforce OAuth failure."""


@dataclass(slots=True)
class SalesforceOAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    login_url: str


@dataclass(slots=True)
class SalesforceOAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    instance_url: str
    scopes: tuple[str, ...]
    token_type: str | None = None


def resolve_salesforce_oauth_client_config(*, redirect_uri: str) -> SalesforceOAuthClientConfig:
    client_id = os.environ.get("AJENDA_SALESFORCE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AJENDA_SALESFORCE_CLIENT_SECRET", "").strip()
    login_url = os.environ.get("AJENDA_SALESFORCE_LOGIN_URL", DEFAULT_SALESFORCE_LOGIN_URL).strip().rstrip("/")
    if not client_id or not client_secret:
        raise SalesforceOAuthError("Set AJENDA_SALESFORCE_CLIENT_ID and AJENDA_SALESFORCE_CLIENT_SECRET")
    return SalesforceOAuthClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri.strip(),
        login_url=login_url or DEFAULT_SALESFORCE_LOGIN_URL,
    )


def salesforce_oauth_scopes() -> tuple[str, ...]:
    raw = os.environ.get("AJENDA_SALESFORCE_OAUTH_SCOPES", "").strip()
    if not raw:
        return DEFAULT_SALESFORCE_OAUTH_SCOPES
    return tuple(part for part in raw.split() if part)


def salesforce_token_url(*, login_url: str) -> str:
    return f"{login_url.rstrip('/')}/services/oauth2/token"


def salesforce_authorization_url(*, login_url: str) -> str:
    return f"{login_url.rstrip('/')}/services/oauth2/authorize"


def build_salesforce_authorization_url(*, client: SalesforceOAuthClientConfig, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "state": state,
        "scope": " ".join(salesforce_oauth_scopes()),
    }
    return f"{salesforce_authorization_url(login_url=client.login_url)}?{urlencode(params)}"


def exchange_salesforce_authorization_code(
    *,
    client: SalesforceOAuthClientConfig,
    code: str,
    timeout_seconds: float = 15.0,
) -> SalesforceOAuthTokenBundle:
    payload = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": client.redirect_uri,
        "client_id": client.client_id,
        "client_secret": client.client_secret,
    }
    return _token_response_to_bundle(_post_token(client=client, payload=payload, timeout_seconds=timeout_seconds))


def refresh_salesforce_access_token(
    *,
    client: SalesforceOAuthClientConfig,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> SalesforceOAuthTokenBundle:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
        "client_id": client.client_id,
        "client_secret": client.client_secret,
    }
    refreshed = _token_response_to_bundle(_post_token(client=client, payload=payload, timeout_seconds=timeout_seconds))
    if refreshed.refresh_token is None:
        return SalesforceOAuthTokenBundle(
            access_token=refreshed.access_token,
            refresh_token=refresh_token.strip(),
            expires_at=refreshed.expires_at,
            instance_url=refreshed.instance_url,
            scopes=refreshed.scopes,
            token_type=refreshed.token_type,
        )
    return refreshed


def instance_host_from_url(instance_url: str) -> str:
    parsed = urlparse(instance_url.strip())
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SalesforceOAuthError("Salesforce instance_url is missing a host")
    return host


def _post_token(
    *,
    client: SalesforceOAuthClientConfig,
    payload: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout_seconds) as http_client:
        response = http_client.post(
            salesforce_token_url(login_url=client.login_url),
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise SalesforceOAuthError(f"Salesforce token endpoint returned HTTP {response.status_code}: {response.text}")
    body = response.json()
    if not isinstance(body, dict):
        raise SalesforceOAuthError("Salesforce token endpoint returned non-object JSON")
    return body


def _token_response_to_bundle(payload: dict[str, Any]) -> SalesforceOAuthTokenBundle:
    access_token = payload.get("access_token")
    instance_url = payload.get("instance_url")
    if not isinstance(access_token, str) or not access_token.strip():
        raise SalesforceOAuthError("Salesforce token response missing access_token")
    if not isinstance(instance_url, str) or not instance_url.strip():
        raise SalesforceOAuthError("Salesforce token response missing instance_url")
    expires_at = None
    issued_at = payload.get("issued_at")
    if isinstance(issued_at, str) and issued_at.isdigit():
        issued_seconds = int(issued_at) / 1000
        expires_at = datetime.fromtimestamp(issued_seconds + 7200, tz=UTC).isoformat()
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    return SalesforceOAuthTokenBundle(
        access_token=access_token.strip(),
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) and refresh_token.strip() else None,
        expires_at=expires_at,
        instance_url=instance_url.strip(),
        scopes=salesforce_oauth_scopes(),
        token_type=token_type.strip() if isinstance(token_type, str) else None,
    )
