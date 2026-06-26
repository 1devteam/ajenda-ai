from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.tools.gmail_provider import GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE
from backend.services.tools.google_oauth_cli import (
    GoogleOAuthClientConfig,
    GoogleOAuthCliError,
    build_google_authorization_url,
    exchange_authorization_code,
    refresh_access_token,
    resolve_gmail_access_token,
    resolve_google_oauth_client_config,
    save_google_oauth_config,
)


def test_resolve_google_oauth_client_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", "cli-client-id")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", "cli-client-secret")

    config = resolve_google_oauth_client_config()

    assert config.client_id == "cli-client-id"
    assert config.client_secret == "cli-client-secret"


def test_resolve_google_oauth_client_config_falls_back_to_oidc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_GOOGLE_CLI_CLIENT_ID", raising=False)
    monkeypatch.delenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("AJENDA_OIDC_CLIENT_ID", "oidc-client-id")
    monkeypatch.setenv("AJENDA_OIDC_CLIENT_SECRET", "oidc-client-secret")

    config = resolve_google_oauth_client_config()

    assert config.client_id == "oidc-client-id"
    assert config.client_secret == "oidc-client-secret"


def test_build_google_authorization_url_includes_gmail_scopes() -> None:
    client = GoogleOAuthClientConfig(client_id="client", client_secret="secret")
    url = build_google_authorization_url(client=client, state="state-123")

    assert "client_id=client" in url
    assert GMAIL_READONLY_SCOPE.replace(":", "%3A").replace("/", "%2F") in url
    assert GMAIL_SEND_SCOPE.replace(":", "%3A").replace("/", "%2F") in url
    assert "state=state-123" in url


def test_exchange_authorization_code_parses_token_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.services.tools.google_oauth_cli._post_token",
        lambda payload, timeout_seconds=15.0: {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
            "scope": f"{GMAIL_READONLY_SCOPE} {GMAIL_SEND_SCOPE}",
            "token_type": "Bearer",
        },
    )

    bundle = exchange_authorization_code(
        client=GoogleOAuthClientConfig(client_id="client", client_secret="secret"),
        code="auth-code",
    )

    assert bundle.access_token == "access-1"
    assert bundle.refresh_token == "refresh-1"
    assert bundle.token_type == "Bearer"
    assert GMAIL_READONLY_SCOPE in bundle.scopes


def test_refresh_access_token_preserves_refresh_token_when_not_rotated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.tools.google_oauth_cli._post_token",
        lambda payload, timeout_seconds=15.0: {
            "access_token": "access-2",
            "expires_in": 3600,
            "scope": GMAIL_READONLY_SCOPE,
            "token_type": "Bearer",
        },
    )

    bundle = refresh_access_token(
        client=GoogleOAuthClientConfig(client_id="client", client_secret="secret"),
        refresh_token="refresh-1",
    )

    assert bundle.access_token == "access-2"
    assert bundle.refresh_token == "refresh-1"


def test_resolve_gmail_access_token_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_E2E_GMAIL_TOKEN", "env-token")

    assert resolve_gmail_access_token() == "env-token"


def test_resolve_gmail_access_token_reads_saved_config(tmp_path: Path) -> None:
    config_path = tmp_path / "google-oauth.yml"
    save_google_oauth_config(
        path=config_path,
        client_id="client",
        token=__import__(
            "backend.services.tools.google_oauth_cli",
            fromlist=["GoogleOAuthTokenBundle"],
        ).GoogleOAuthTokenBundle(
            access_token="saved-token",
            refresh_token=None,
            expires_at="2099-01-01T00:00:00+00:00",
            scopes=(GMAIL_READONLY_SCOPE,),
        ),
    )

    assert resolve_gmail_access_token(config_path=config_path, auto_refresh=False) == "saved-token"


def test_init_client_json_parses_installed_section(tmp_path: Path) -> None:
    client_json = tmp_path / "client.json"
    client_json.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "desktop-client",
                    "client_secret": "desktop-secret",
                }
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(client_json.read_text(encoding="utf-8"))
    installed = payload["installed"]

    assert installed["client_id"] == "desktop-client"
    assert installed["client_secret"] == "desktop-secret"


def test_resolve_google_oauth_client_config_requires_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AJENDA_GOOGLE_CLI_CLIENT_ID", raising=False)
    monkeypatch.delenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("AJENDA_OIDC_CLIENT_ID", raising=False)
    monkeypatch.delenv("AJENDA_OIDC_CLIENT_SECRET", raising=False)

    with pytest.raises(GoogleOAuthCliError, match="AJENDA_GOOGLE_CLI_CLIENT_ID"):
        resolve_google_oauth_client_config()
