"""LinkedIn OAuth client for product credential connect and runtime refresh."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

LINKEDIN_OAUTH_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
DEFAULT_LINKEDIN_OAUTH_SCOPES = ("openid", "profile", "email")
TOKEN_REFRESH_SKEW_SECONDS = 60


class LinkedInOAuthClientError(ValueError):
    """Deterministic LinkedIn OAuth failure."""


@dataclass(slots=True)
class LinkedInOAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(slots=True)
class LinkedInOAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    scopes: tuple[str, ...]
    token_type: str | None = None


def resolve_linkedin_oauth_client_config(*, redirect_uri: str) -> LinkedInOAuthClientConfig:
    client_id = os.environ.get("AJENDA_LINKEDIN_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AJENDA_LINKEDIN_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise LinkedInOAuthClientError(
            "Set AJENDA_LINKEDIN_CLIENT_ID and AJENDA_LINKEDIN_CLIENT_SECRET for LinkedIn OAuth"
        )
    normalized_redirect = redirect_uri.strip()
    if not normalized_redirect:
        raise LinkedInOAuthClientError("LinkedIn OAuth redirect_uri is required")
    return LinkedInOAuthClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=normalized_redirect,
    )


def linkedin_oauth_scopes() -> tuple[str, ...]:
    raw = os.environ.get("AJENDA_LINKEDIN_OAUTH_SCOPES", "").strip()
    if not raw:
        return DEFAULT_LINKEDIN_OAUTH_SCOPES
    return tuple(part for part in raw.split() if part)


def build_linkedin_authorization_url(*, client: LinkedInOAuthClientConfig, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "state": state,
        "scope": " ".join(linkedin_oauth_scopes()),
    }
    return f"{LINKEDIN_OAUTH_AUTH_URL}?{urlencode(params)}"


def exchange_linkedin_authorization_code(
    *,
    client: LinkedInOAuthClientConfig,
    code: str,
    timeout_seconds: float = 15.0,
) -> LinkedInOAuthTokenBundle:
    payload = {
        "grant_type": "authorization_code",
        "code": code.strip(),
        "redirect_uri": client.redirect_uri,
        "client_id": client.client_id,
        "client_secret": client.client_secret,
    }
    return _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))


def refresh_linkedin_access_token(
    *,
    client: LinkedInOAuthClientConfig,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> LinkedInOAuthTokenBundle:
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
        "client_id": client.client_id,
        "client_secret": client.client_secret,
    }
    refreshed = _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))
    if refreshed.refresh_token is None:
        return LinkedInOAuthTokenBundle(
            access_token=refreshed.access_token,
            refresh_token=refresh_token.strip(),
            expires_at=refreshed.expires_at,
            scopes=refreshed.scopes,
            token_type=refreshed.token_type,
        )
    return refreshed


def _post_token(payload: dict[str, str], *, timeout_seconds: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            LINKEDIN_OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise LinkedInOAuthClientError(f"LinkedIn token endpoint returned HTTP {response.status_code}: {response.text}")
    try:
        body = response.json()
    except ValueError as exc:
        raise LinkedInOAuthClientError("LinkedIn token endpoint returned non-JSON") from exc
    if not isinstance(body, dict):
        raise LinkedInOAuthClientError("LinkedIn token endpoint returned invalid payload")
    return body


def _token_response_to_bundle(payload: dict[str, Any]) -> LinkedInOAuthTokenBundle:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise LinkedInOAuthClientError("LinkedIn token response missing access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    expires_at = None
    if isinstance(expires_in, int) and expires_in > 0:
        expires_at = (datetime.now(tz=UTC) + timedelta(seconds=expires_in)).isoformat()
    scope_raw = payload.get("scope")
    scopes: tuple[str, ...] = ()
    if isinstance(scope_raw, str) and scope_raw.strip():
        scopes = tuple(part for part in scope_raw.split() if part)
    token_type = payload.get("token_type")
    return LinkedInOAuthTokenBundle(
        access_token=access_token.strip(),
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) and refresh_token.strip() else None,
        expires_at=expires_at,
        scopes=scopes or linkedin_oauth_scopes(),
        token_type=token_type.strip() if isinstance(token_type, str) else None,
    )
