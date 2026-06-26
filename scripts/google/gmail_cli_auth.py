#!/usr/bin/env python3
"""Authenticate Gmail for Ajenda CLI and store tokens locally."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from backend.services.tools.gmail_provider import DEFAULT_GMAIL_CLI_REDIRECT_URI, required_gmail_scopes
from backend.services.tools.google_oauth_cli import (
    DEFAULT_GOOGLE_OAUTH_CONFIG_PATH,
    GoogleOAuthClientConfig,
    GoogleOAuthCliError,
    GoogleOAuthTokenBundle,
    build_google_authorization_url,
    exchange_authorization_code,
    google_oauth_setup_instructions,
    load_google_oauth_config,
    resolve_gmail_access_token,
    resolve_google_oauth_client_config,
    save_google_oauth_config,
)

DEFAULT_GCP_PROJECT_NUMBER = "38457754291"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    authorization_code: str | None = None
    oauth_error: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != urlparse(DEFAULT_GMAIL_CLI_REDIRECT_URI).path:
            self.send_response(404)
            self.end_headers()
            return
        query = parse_qs(parsed.query)
        if "error" in query:
            _OAuthCallbackHandler.oauth_error = query["error"][0]
        if "code" in query:
            _OAuthCallbackHandler.authorization_code = query["code"][0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Ajenda Google auth complete</h1>"
            b"<p>You can close this tab and return to the terminal.</p></body></html>"
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ajenda Gmail CLI OAuth helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Print Google Cloud OAuth client setup steps")
    setup.add_argument("--project", default=DEFAULT_GCP_PROJECT_NUMBER)

    auth = subparsers.add_parser("auth", help="Run browser OAuth and store Gmail tokens")
    auth.add_argument("--no-browser", action="store_true", help="Print auth URL instead of opening a browser")
    auth.add_argument(
        "--code",
        help="Authorization code from redirect (use with --no-browser after approving in Google)",
    )
    auth.add_argument(
        "--config-path",
        default=str(DEFAULT_GOOGLE_OAUTH_CONFIG_PATH),
        help=f"Token output path (default: {DEFAULT_GOOGLE_OAUTH_CONFIG_PATH})",
    )

    status = subparsers.add_parser("status", help="Show stored token status")
    status.add_argument(
        "--config-path",
        default=str(DEFAULT_GOOGLE_OAUTH_CONFIG_PATH),
        help=f"Token config path (default: {DEFAULT_GOOGLE_OAUTH_CONFIG_PATH})",
    )

    token = subparsers.add_parser("token", help="Print a usable access token (refreshing if needed)")
    token.add_argument(
        "--config-path",
        default=str(DEFAULT_GOOGLE_OAUTH_CONFIG_PATH),
        help=f"Token config path (default: {DEFAULT_GOOGLE_OAUTH_CONFIG_PATH})",
    )

    init_client = subparsers.add_parser(
        "init-client",
        help="Load Desktop client JSON from Google Cloud into local env exports",
    )
    init_client.add_argument(
        "client_json",
        nargs="?",
        default=str(Path.home() / ".ajenda" / "google-cli-client.json"),
        help="Path to downloaded OAuth client JSON",
    )

    return parser.parse_args()


def _command_setup(project: str) -> int:
    print(google_oauth_setup_instructions(project_number=project))
    return 0


def _command_init_client(client_json: str) -> int:
    path = Path(client_json).expanduser()
    if not path.is_file():
        print(f"Missing client JSON: {path}", file=sys.stderr)
        print("Create a Desktop OAuth client in Google Cloud and download the JSON.", file=sys.stderr)
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    installed = payload.get("installed") if isinstance(payload, dict) else None
    web = payload.get("web") if isinstance(payload, dict) else None
    section = installed if isinstance(installed, dict) else web
    if not isinstance(section, dict):
        print("Expected Google client JSON with installed or web section", file=sys.stderr)
        return 2
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        print("Client JSON missing client_id/client_secret", file=sys.stderr)
        return 2
    path.chmod(0o600)
    print("Loaded Google CLI OAuth client.")
    print(f"export AJENDA_GOOGLE_CLI_CLIENT_ID={client_id}")
    print(f"export AJENDA_GOOGLE_CLI_CLIENT_SECRET={client_secret}")
    print(f"export AJENDA_GOOGLE_CLI_REDIRECT_URI={DEFAULT_GMAIL_CLI_REDIRECT_URI}")
    return 0


def _save_auth_bundle(*, client: GoogleOAuthClientConfig, bundle: GoogleOAuthTokenBundle, config_path: str) -> int:
    account_email = _lookup_account_email(bundle.access_token)
    saved = GoogleOAuthTokenBundle(
        access_token=bundle.access_token,
        refresh_token=bundle.refresh_token,
        expires_at=bundle.expires_at,
        scopes=bundle.scopes or required_gmail_scopes(),
        token_type=bundle.token_type,
        account_email=account_email,
    )
    output_path = Path(config_path).expanduser()
    save_google_oauth_config(
        path=output_path,
        client_id=client.client_id,
        token=saved,
        redirect_uri=client.redirect_uri,
    )
    print(f"Saved Gmail OAuth token to {output_path}")
    if account_email:
        print(f"Account: {account_email}")
    if saved.refresh_token:
        print("Refresh token stored.")
    return 0


def _command_auth(*, no_browser: bool, code: str | None, config_path: str) -> int:
    try:
        client = resolve_google_oauth_client_config()
    except GoogleOAuthCliError as exc:
        print(str(exc), file=sys.stderr)
        print("Run: python scripts/google/gmail_cli_auth.py setup", file=sys.stderr)
        return 2

    if code and code.strip():
        bundle = exchange_authorization_code(client=client, code=code.strip())
        return _save_auth_bundle(client=client, bundle=bundle, config_path=config_path)

    state = secrets.token_urlsafe(24)
    auth_url = build_google_authorization_url(client=client, state=state)
    if no_browser:
        print(auth_url)
        print(
            "Open the URL, approve access, then run:\n"
            "  python scripts/google/gmail_cli_auth.py auth --code 'PASTE_CODE_HERE'"
        )
        return 0

    _OAuthCallbackHandler.authorization_code = None
    _OAuthCallbackHandler.oauth_error = None
    redirect = urlparse(client.redirect_uri)
    server = HTTPServer((redirect.hostname or "127.0.0.1", redirect.port or 8765), _OAuthCallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print(f"Opening browser for Gmail OAuth ({', '.join(required_gmail_scopes())})")
    webbrowser.open(auth_url)
    thread.join(timeout=180)
    server.server_close()

    if _OAuthCallbackHandler.oauth_error:
        print(f"OAuth error: {_OAuthCallbackHandler.oauth_error}", file=sys.stderr)
        return 2
    if not _OAuthCallbackHandler.authorization_code:
        print("Timed out waiting for OAuth callback", file=sys.stderr)
        return 2

    bundle = exchange_authorization_code(client=client, code=_OAuthCallbackHandler.authorization_code)
    return _save_auth_bundle(client=client, bundle=bundle, config_path=config_path)


def _command_status(config_path: str) -> int:
    path = Path(config_path).expanduser()
    if not path.is_file():
        print(f"No token file at {path}")
        return 1
    stored = load_google_oauth_config(path)
    print(f"config: {path}")
    print(f"client_id: {stored.get('client_id', '(unknown)')}")
    print(f"account_email: {stored.get('account_email', '(unknown)')}")
    print(f"expires_at: {stored.get('expires_at', '(unknown)')}")
    scopes = stored.get("scopes")
    if isinstance(scopes, list):
        print("scopes:")
        for scope in scopes:
            print(f"  - {scope}")
    print(f"has_refresh_token: {bool(stored.get('refresh_token'))}")
    return 0


def _command_token(config_path: str) -> int:
    token = resolve_gmail_access_token(config_path=Path(config_path).expanduser())
    if not token:
        print("No Gmail token found. Run auth first or set AJENDA_E2E_GMAIL_TOKEN.", file=sys.stderr)
        return 2
    print(token)
    return 0


def _lookup_account_email(access_token: str) -> str | None:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            return None
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    email = payload.get("email") if isinstance(payload, dict) else None
    return email.strip() if isinstance(email, str) and email.strip() else None


def main() -> int:
    args = _parse_args()
    if args.command == "setup":
        return _command_setup(args.project)
    if args.command == "init-client":
        return _command_init_client(args.client_json)
    if args.command == "auth":
        return _command_auth(no_browser=args.no_browser, code=args.code, config_path=args.config_path)
    if args.command == "status":
        return _command_status(args.config_path)
    if args.command == "token":
        return _command_token(args.config_path)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())