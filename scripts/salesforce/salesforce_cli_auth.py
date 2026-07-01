#!/usr/bin/env python3
"""Authenticate Salesforce for Ajenda CLI / E2E and store tokens locally."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.services.credentials.salesforce_oauth_client import (
    DEFAULT_SALESFORCE_LOGIN_URL,
    SalesforceOAuthClientConfig,
    SalesforceOAuthError,
    SalesforceOAuthTokenBundle,
    build_salesforce_authorization_url,
    exchange_salesforce_authorization_code,
    instance_host_from_url,
    resolve_salesforce_oauth_client_config,
    salesforce_oauth_scopes,
)
from backend.services.credentials.salesforce_runtime_token import (
    resolve_salesforce_credential_secret,
    serialize_salesforce_oauth_secret,
)

DEFAULT_SALESFORCE_CLI_REDIRECT_URI = "http://127.0.0.1:8766/oauth/callback"
DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH = Path.home() / ".ajenda" / "salesforce-oauth.json"
DEFAULT_SALESFORCE_CLI_ENV_PATH = Path.home() / ".ajenda" / "salesforce-cli.env"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    authorization_code: str | None = None
    oauth_error: str | None = None
    callback_path: str = urlparse(DEFAULT_SALESFORCE_CLI_REDIRECT_URI).path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != self.callback_path:
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
            b"<html><body><h1>Ajenda Salesforce auth complete</h1>"
            b"<p>You can close this tab and return to the terminal.</p></body></html>"
        )

    def log_message(self, format: str, *args: Any) -> None:
        return


def salesforce_oauth_setup_instructions() -> str:
    redirect_uri = resolve_salesforce_cli_redirect_uri()
    scopes = " ".join(salesforce_oauth_scopes())
    return (
        "Connect Salesforce through Ajenda Credentials UI (recommended):\n"
        "1. Salesforce Setup -> App Manager -> New Connected App / External Client App\n"
        "2. Enable OAuth Settings\n"
        "3. Callback URL (required for product UI):\n"
        "     http://localhost:5173/credentials/salesforce/callback\n"
        f"4. Selected OAuth scopes: {scopes}\n"
        "5. Copy Consumer Key / Client ID and Consumer Secret / Client Secret into backend env:\n"
        "     AJENDA_SALESFORCE_CLIENT_ID\n"
        "     AJENDA_SALESFORCE_CLIENT_SECRET\n"
        "   For sandbox orgs also set AJENDA_SALESFORCE_LOGIN_URL=https://test.salesforce.com\n"
        "6. Start Ajenda frontend + backend, open Credentials -> Connect Salesforce\n"
        "   OAuth tokens are stored encrypted per tenant (never returned by the API).\n"
        "\n"
        "Optional CLI / live E2E bridge (when UI is unavailable):\n"
        f"7. Save CLI client env to {DEFAULT_SALESFORCE_CLI_ENV_PATH} (chmod 600):\n"
        "     export AJENDA_SALESFORCE_CLIENT_ID='...'\n"
        "     export AJENDA_SALESFORCE_CLIENT_SECRET='...'\n"
        f"     export AJENDA_SALESFORCE_CLI_REDIRECT_URI='{redirect_uri}'\n"
        f"   CLI callback URL (optional): {DEFAULT_SALESFORCE_CLI_REDIRECT_URI}\n"
        f"8. Run: python scripts/salesforce/salesforce_cli_auth.py auth\n"
        f"   Tokens are stored at {DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH} (never commit).\n"
        "9. Register the CLI token to a tenant via provider_oauth_bridge:\n"
        "     python scripts/ajenda/provider_oauth_bridge.py register salesforce \\\n"
        "       --tenant-id TENANT_UUID --api-key KEY_ID.SECRET \\\n"
        f"       --oauth-json {DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH}\n"
    )


def resolve_salesforce_cli_redirect_uri() -> str:
    configured = os.environ.get("AJENDA_SALESFORCE_CLI_REDIRECT_URI", "").strip()
    if configured:
        return configured
    product = os.environ.get("AJENDA_SALESFORCE_OAUTH_REDIRECT_URI", "").strip()
    if product and "5173" in product:
        return DEFAULT_SALESFORCE_CLI_REDIRECT_URI
    return DEFAULT_SALESFORCE_CLI_REDIRECT_URI


def resolve_salesforce_cli_client_config() -> SalesforceOAuthClientConfig:
    return resolve_salesforce_oauth_client_config(redirect_uri=resolve_salesforce_cli_redirect_uri())


def load_salesforce_oauth_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SalesforceOAuthError(f"Salesforce OAuth config not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SalesforceOAuthError(f"Salesforce OAuth config must be JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SalesforceOAuthError(f"Salesforce OAuth config must be a JSON object: {path}")
    return payload


def save_salesforce_oauth_config(*, path: Path, bundle: SalesforceOAuthTokenBundle) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_salesforce_oauth_secret(bundle=bundle) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _load_shell_exports(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        if key and value:
            os.environ[key] = value.strip("'\"")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ajenda Salesforce CLI OAuth helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="Print Salesforce External Client App setup steps")

    auth = subparsers.add_parser("auth", help="Run browser OAuth and store Salesforce tokens")
    auth.add_argument("--no-browser", action="store_true", help="Print auth URL instead of opening a browser")
    auth.add_argument(
        "--code",
        help="Authorization code from redirect (use with --no-browser after approving in Salesforce)",
    )
    auth.add_argument(
        "--output-path",
        default=str(DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH),
        help=f"Token output path (default: {DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH})",
    )

    status = subparsers.add_parser("status", help="Show stored token status")
    status.add_argument(
        "--config-path",
        default=str(DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH),
        help=f"Token config path (default: {DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH})",
    )

    token = subparsers.add_parser("token", help="Print usable access token (refreshing if needed)")
    token.add_argument(
        "--config-path",
        default=str(DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH),
        help=f"Token config path (default: {DEFAULT_SALESFORCE_OAUTH_CONFIG_PATH})",
    )

    return parser.parse_args()


def _command_setup() -> int:
    print(salesforce_oauth_setup_instructions())
    return 0


def _save_auth_bundle(*, bundle: SalesforceOAuthTokenBundle, output_path: str) -> int:
    path = Path(output_path).expanduser()
    save_salesforce_oauth_config(path=path, bundle=bundle)
    host = instance_host_from_url(bundle.instance_url)
    print(f"Saved Salesforce OAuth token to {path}")
    print(f"instance_host: {host}")
    if bundle.refresh_token:
        print("Refresh token stored.")
    return 0


def _command_auth(*, no_browser: bool, code: str | None, output_path: str) -> int:
    try:
        client = resolve_salesforce_cli_client_config()
    except SalesforceOAuthError as exc:
        print(str(exc), file=sys.stderr)
        print("Run: python scripts/salesforce/salesforce_cli_auth.py setup", file=sys.stderr)
        return 2

    if code and code.strip():
        bundle = exchange_salesforce_authorization_code(client=client, code=code.strip())
        return _save_auth_bundle(bundle=bundle, output_path=output_path)

    state = secrets.token_urlsafe(24)
    auth_url = build_salesforce_authorization_url(client=client, state=state)
    if no_browser:
        print(auth_url)
        print(
            "Open the URL, approve access, then run:\n"
            "  python scripts/salesforce/salesforce_cli_auth.py auth --code 'PASTE_CODE_HERE'"
        )
        return 0

    redirect = urlparse(client.redirect_uri)
    _OAuthCallbackHandler.callback_path = redirect.path or "/oauth/callback"
    _OAuthCallbackHandler.authorization_code = None
    _OAuthCallbackHandler.oauth_error = None
    server = HTTPServer((redirect.hostname or "127.0.0.1", redirect.port or 8766), _OAuthCallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    print(f"Opening browser for Salesforce OAuth ({', '.join(salesforce_oauth_scopes())})")
    print(f"Callback: {client.redirect_uri}")
    webbrowser.open(auth_url)
    thread.join(timeout=180)
    server.server_close()

    if _OAuthCallbackHandler.oauth_error:
        print(f"OAuth error: {_OAuthCallbackHandler.oauth_error}", file=sys.stderr)
        return 2
    if not _OAuthCallbackHandler.authorization_code:
        print("Timed out waiting for OAuth callback", file=sys.stderr)
        print("Retry with --no-browser and paste the code from the redirect URL.", file=sys.stderr)
        return 2

    bundle = exchange_salesforce_authorization_code(
        client=client,
        code=_OAuthCallbackHandler.authorization_code,
    )
    return _save_auth_bundle(bundle=bundle, output_path=output_path)


def _command_status(config_path: str) -> int:
    path = Path(config_path).expanduser()
    if not path.is_file():
        print(f"No token file at {path}")
        return 1
    stored = load_salesforce_oauth_config(path)
    print(f"config: {path}")
    print(f"instance_url: {stored.get('instance_url', '(unknown)')}")
    print(f"expires_at: {stored.get('expires_at', '(unknown)')}")
    scopes = stored.get("scopes")
    if isinstance(scopes, list):
        print("scopes:")
        for scope in scopes:
            print(f"  - {scope}")
    print(f"has_refresh_token: {bool(stored.get('refresh_token'))}")
    return 0


def _command_token(config_path: str) -> int:
    path = Path(config_path).expanduser()
    if not path.is_file():
        print("No Salesforce token found. Run auth first.", file=sys.stderr)
        return 2
    secret = path.read_text(encoding="utf-8").strip()
    try:
        resolved = resolve_salesforce_credential_secret(
            secret,
            redirect_uri=resolve_salesforce_cli_redirect_uri(),
        )
    except Exception as exc:
        print(f"Failed to resolve Salesforce token: {exc}", file=sys.stderr)
        return 2
    if resolved.updated_secret:
        path.write_text(resolved.updated_secret + "\n", encoding="utf-8")
        path.chmod(0o600)
    print(resolved.access_token)
    return 0


def main() -> int:
    _load_shell_exports(DEFAULT_SALESFORCE_CLI_ENV_PATH)
    args = _parse_args()
    if args.command == "setup":
        return _command_setup()
    if args.command == "auth":
        return _command_auth(no_browser=args.no_browser, code=args.code, output_path=args.output_path)
    if args.command == "status":
        return _command_status(args.config_path)
    if args.command == "token":
        return _command_token(args.config_path)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())