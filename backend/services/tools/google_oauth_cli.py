"""Local Google OAuth token storage and refresh for Ajenda CLI / E2E flows."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import yaml  # type: ignore[import-untyped]

from backend.services.tools.gmail_provider import (
    DEFAULT_GMAIL_CLI_REDIRECT_URI,
    GOOGLE_OAUTH_AUTH_URL,
    GOOGLE_OAUTH_TOKEN_URL,
    required_gmail_scopes,
)

DEFAULT_GOOGLE_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "google-oauth.yml"
TOKEN_REFRESH_SKEW_SECONDS = 60


class GoogleOAuthCliError(ValueError):
    """Deterministic CLI OAuth configuration or token failure."""


@dataclass(slots=True)
class GoogleOAuthClientConfig:
    client_id: str
    client_secret: str
    redirect_uri: str = DEFAULT_GMAIL_CLI_REDIRECT_URI


@dataclass(slots=True)
class GoogleOAuthTokenBundle:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    scopes: tuple[str, ...]
    token_type: str | None = None
    account_email: str | None = None


def resolve_google_oauth_client_config() -> GoogleOAuthClientConfig:
    """Resolve CLI OAuth client credentials from env (never from committed files)."""

    client_id = (
        os.environ.get("AJENDA_GOOGLE_CONNECTOR_CLIENT_ID", "").strip()
        or os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_ID", "").strip()
        or os.environ.get("AJENDA_OIDC_CLIENT_ID", "").strip()
    )
    client_secret = (
        os.environ.get("AJENDA_GOOGLE_CONNECTOR_CLIENT_SECRET", "").strip()
        or os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "").strip()
        or os.environ.get("AJENDA_OIDC_CLIENT_SECRET", "").strip()
    )
    redirect_uri = os.environ.get("AJENDA_GOOGLE_CLI_REDIRECT_URI", DEFAULT_GMAIL_CLI_REDIRECT_URI).strip()
    if not client_id or not client_secret:
        raise GoogleOAuthCliError(
            "Set AJENDA_GOOGLE_CONNECTOR_CLIENT_ID and AJENDA_GOOGLE_CONNECTOR_CLIENT_SECRET "
            "(or AJENDA_GOOGLE_CLI_CLIENT_ID/AJENDA_GOOGLE_CLI_CLIENT_SECRET for development; OIDC fallback is legacy-only)"
        )
    return GoogleOAuthClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri or DEFAULT_GMAIL_CLI_REDIRECT_URI,
    )


def build_google_authorization_url(
    *,
    client: GoogleOAuthClientConfig,
    state: str,
    scopes: tuple[str, ...] | None = None,
    pick_account: bool = False,
) -> str:
    scope_values = scopes or required_gmail_scopes()
    params = {
        "client_id": client.client_id,
        "response_type": "code",
        "scope": " ".join(scope_values),
        "redirect_uri": client.redirect_uri,
        "access_type": "offline",
        "prompt": "select_account consent" if pick_account else "consent",
        "state": state,
    }
    return f"{GOOGLE_OAUTH_AUTH_URL}?{urlencode(params)}"


def exchange_authorization_code(
    *,
    client: GoogleOAuthClientConfig,
    code: str,
    timeout_seconds: float = 15.0,
) -> GoogleOAuthTokenBundle:
    payload = {
        "code": code.strip(),
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "redirect_uri": client.redirect_uri,
        "grant_type": "authorization_code",
    }
    return _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))


def refresh_access_token(
    *,
    client: GoogleOAuthClientConfig,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> GoogleOAuthTokenBundle:
    payload = {
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "refresh_token": refresh_token.strip(),
        "grant_type": "refresh_token",
    }
    refreshed = _token_response_to_bundle(_post_token(payload, timeout_seconds=timeout_seconds))
    if refreshed.refresh_token is None:
        return GoogleOAuthTokenBundle(
            access_token=refreshed.access_token,
            refresh_token=refresh_token.strip(),
            expires_at=refreshed.expires_at,
            scopes=refreshed.scopes,
            token_type=refreshed.token_type,
            account_email=refreshed.account_email,
        )
    return refreshed


def save_google_oauth_config(
    *,
    path: Path,
    client_id: str,
    token: GoogleOAuthTokenBundle,
    redirect_uri: str = DEFAULT_GMAIL_CLI_REDIRECT_URI,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "account_email": token.account_email,
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": token.expires_at,
        "scopes": list(token.scopes),
        "token_type": token.token_type,
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    path.chmod(0o600)


def load_google_oauth_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise GoogleOAuthCliError(f"OAuth config not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GoogleOAuthCliError(f"failed to read OAuth config: {path}") from exc
    if not isinstance(loaded, dict):
        raise GoogleOAuthCliError(f"OAuth config must be a mapping: {path}")
    return loaded


def resolve_gmail_access_token(
    *,
    config_path: Path | None = None,
    explicit_token: str | None = None,
    auto_refresh: bool = True,
    prefer_config_refresh: bool = False,
) -> str | None:
    if not prefer_config_refresh:
        token = (explicit_token or os.environ.get("AJENDA_E2E_GMAIL_TOKEN", "")).strip()
        if token:
            return token

    path = config_path or DEFAULT_GOOGLE_OAUTH_CONFIG_PATH
    if not path.is_file():
        return None

    try:
        stored = load_google_oauth_config(path)
    except GoogleOAuthCliError:
        return None

    access_token = stored.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        return None

    if not auto_refresh:
        return access_token.strip()

    expires_at = stored.get("expires_at")
    refresh_token = stored.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token.strip() and _token_expired(expires_at):
        try:
            client = resolve_google_oauth_client_config()
        except GoogleOAuthCliError:
            return access_token.strip()
        refreshed = refresh_access_token(client=client, refresh_token=refresh_token)
        client_id = stored.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip():
            client_id = client.client_id
        redirect_uri = stored.get("redirect_uri")
        save_google_oauth_config(
            path=path,
            client_id=client_id,
            token=GoogleOAuthTokenBundle(
                access_token=refreshed.access_token,
                refresh_token=refreshed.refresh_token,
                expires_at=refreshed.expires_at,
                scopes=refreshed.scopes or tuple(required_gmail_scopes()),
                token_type=refreshed.token_type,
                account_email=stored.get("account_email") if isinstance(stored.get("account_email"), str) else None,
            ),
            redirect_uri=str(redirect_uri)
            if isinstance(redirect_uri, str) and redirect_uri.strip()
            else client.redirect_uri,
        )
        return refreshed.access_token.strip()

    return access_token.strip()


def google_oauth_setup_instructions(*, project_number: str | None = None) -> str:
    project = project_number or "YOUR_GCP_PROJECT_NUMBER"
    redirect_uri = DEFAULT_GMAIL_CLI_REDIRECT_URI
    scopes = "\n".join(f"  - {scope}" for scope in required_gmail_scopes())
    return (
        "Create or extend a Google OAuth client for Ajenda CLI Gmail auth:\n"
        f"1. Open https://console.cloud.google.com/apis/credentials?project={project}\n"
        "2. Enable Gmail API: https://console.cloud.google.com/apis/library/gmail.googleapis.com\n"
        "3. OAuth consent screen -> add scopes:\n"
        f"{scopes}\n"
        "4. Choose one client strategy:\n"
        "   A) Reuse your existing Web client (OIDC login client):\n"
        f"      - Add authorized redirect URI: {redirect_uri}\n"
        "      - Export AJENDA_GOOGLE_CLI_CLIENT_ID / AJENDA_GOOGLE_CLI_CLIENT_SECRET\n"
        "        (or reuse AJENDA_OIDC_CLIENT_ID / AJENDA_OIDC_CLIENT_SECRET locally)\n"
        "   B) Create a new OAuth client -> Desktop app (recommended for CLI-only use)\n"
        "      - Download JSON to ~/.ajenda/google-cli-client.json (chmod 600)\n"
        "      - Export AJENDA_GOOGLE_CLI_CLIENT_ID / AJENDA_GOOGLE_CLI_CLIENT_SECRET from that file\n"
        f"5. Run: python scripts/google/gmail_cli_auth.py auth\n"
        f"   Tokens are stored at {DEFAULT_GOOGLE_OAUTH_CONFIG_PATH} (never commit).\n"
    )


def _post_token(payload: dict[str, str], *, timeout_seconds: float) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        raise GoogleOAuthCliError("Google token endpoint request failed") from exc
    if response.status_code >= 400:
        detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
        raise GoogleOAuthCliError(f"Google token exchange failed: {detail}")
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise GoogleOAuthCliError("Google token endpoint returned non-JSON response") from exc
    if not isinstance(body, dict):
        raise GoogleOAuthCliError("Google token endpoint returned unexpected payload")
    return body


def _token_response_to_bundle(body: dict[str, Any]) -> GoogleOAuthTokenBundle:
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise GoogleOAuthCliError("Google token response missing access_token")
    refresh_token = body.get("refresh_token")
    expires_in = body.get("expires_in")
    expires_at = None
    if isinstance(expires_in, int | float):
        expires_at = (datetime.now(tz=UTC) + timedelta(seconds=float(expires_in))).isoformat()
    scope_raw = body.get("scope", "")
    scopes: tuple[str, ...] = ()
    if isinstance(scope_raw, str) and scope_raw.strip():
        scopes = tuple(part for part in scope_raw.split() if part)
    token_type = body.get("token_type")
    return GoogleOAuthTokenBundle(
        access_token=access_token.strip(),
        refresh_token=refresh_token.strip() if isinstance(refresh_token, str) and refresh_token.strip() else None,
        expires_at=expires_at,
        scopes=scopes,
        token_type=token_type.strip() if isinstance(token_type, str) and token_type.strip() else None,
    )


def _token_expired(expires_at: Any) -> bool:
    if not isinstance(expires_at, str) or not expires_at.strip():
        return False
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(tz=UTC) + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS)
