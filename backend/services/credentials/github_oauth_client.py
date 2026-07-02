"""GitHub OAuth client for product credential connect and runtime refresh."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEFAULT_GITHUB_OAUTH_SCOPES = ("read:user",)
TOKEN_REFRESH_SKEW_SECONDS = 60


class GitHubOAuthClientError(ValueError):
    """Deterministic GitHub OAuth failure."""


@dataclass(slots=True)
class GitHubOAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(slots=True)
class GitHubOAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    scopes: tuple[str, ...]
    token_type: str | None = None


def resolve_github_oauth_client_config(*, redirect_uri: str) -> GitHubOAuthClientConfig:
    client_id = os.environ.get("AJENDA_GITHUB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("AJENDA_GITHUB_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise GitHubOAuthClientError("Set AJENDA_GITHUB_CLIENT_ID and AJENDA_GITHUB_CLIENT_SECRET for GitHub OAuth")
    normalized_redirect = redirect_uri.strip()
    if not normalized_redirect:
        raise GitHubOAuthClientError("GitHub OAuth redirect_uri is required")
    return GitHubOAuthClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=normalized_redirect,
    )


def github_oauth_scopes() -> tuple[str, ...]:
    raw = os.environ.get("AJENDA_GITHUB_OAUTH_SCOPES", "").strip()
    if not raw:
        return DEFAULT_GITHUB_OAUTH_SCOPES
    return tuple(part for part in raw.split() if part)


def build_github_authorization_url(*, client: GitHubOAuthClientConfig, state: str) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "state": state,
        "scope": " ".join(github_oauth_scopes()),
    }
    return f"{GITHUB_OAUTH_AUTH_URL}?{urlencode(params)}"


def exchange_github_authorization_code(
    *,
    client: GitHubOAuthClientConfig,
    code: str,
    timeout_seconds: float = 15.0,
) -> GitHubOAuthTokenBundle:
    payload = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "code": code.strip(),
        "redirect_uri": client.redirect_uri,
    }
    return _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))


def refresh_github_access_token(
    *,
    client: GitHubOAuthClientConfig,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> GitHubOAuthTokenBundle:
    payload = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
    }
    refreshed = _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))
    if refreshed.refresh_token is None:
        return GitHubOAuthTokenBundle(
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
            GITHUB_OAUTH_TOKEN_URL,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    if response.status_code >= 400:
        raise GitHubOAuthClientError(f"GitHub token endpoint returned HTTP {response.status_code}: {response.text}")
    try:
        body = response.json()
    except ValueError as exc:
        raise GitHubOAuthClientError("GitHub token endpoint returned non-JSON") from exc
    if not isinstance(body, dict):
        raise GitHubOAuthClientError("GitHub token endpoint returned invalid payload")
    return body


def _token_response_to_bundle(payload: dict[str, Any]) -> GitHubOAuthTokenBundle:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GitHubOAuthClientError("GitHub token response missing access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    expires_at = None
    if isinstance(expires_in, int) and expires_in > 0:
        expires_at = (datetime.now(tz=UTC) + timedelta(seconds=expires_in)).isoformat()
    scope_raw = payload.get("scope")
    scopes: tuple[str, ...] = ()
    if isinstance(scope_raw, str) and scope_raw.strip():
        scopes = tuple(part for part in scope_raw.replace(",", " ").split() if part)
    token_type = payload.get("token_type")
    return GitHubOAuthTokenBundle(
        access_token=access_token.strip(),
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) and refresh_token.strip() else None,
        expires_at=expires_at,
        scopes=scopes or github_oauth_scopes(),
        token_type=token_type.strip() if isinstance(token_type, str) else None,
    )
