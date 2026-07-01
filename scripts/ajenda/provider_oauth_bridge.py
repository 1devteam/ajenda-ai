#!/usr/bin/env python3
"""Register local CLI OAuth token files with a tenant via the Credentials API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]

PROVIDER_REGISTRATIONS: dict[str, dict[str, str]] = {
    "salesforce": {
        "credential_id": "salesforce-read",
        "provider": "external_read_provider",
        "integration": "salesforce",
    },
    "gmail": {
        "credential_id": "gmail-email",
        "provider": "external_email",
        "integration": "gmail",
    },
    "linkedin": {
        "credential_id": "linkedin-read",
        "provider": "external_read_provider",
        "integration": "linkedin",
    },
    "google-calendar": {
        "credential_id": "google-calendar-read",
        "provider": "external_read_provider",
        "integration": "google_calendar",
    },
    "github": {
        "credential_id": "github-read",
        "provider": "external_read_provider",
        "integration": "github",
    },
}

DEFAULT_OAUTH_PATHS: dict[str, Path] = {
    "salesforce": Path.home() / ".ajenda" / "salesforce-oauth.json",
    "gmail": Path.home() / ".ajenda" / "google-oauth.yml",
    "linkedin": Path.home() / ".ajenda" / "linkedin-oauth.json",
    "google-calendar": Path.home() / ".ajenda" / "google-calendar-oauth.json",
    "github": Path.home() / ".ajenda" / "github-oauth.json",
}


def _load_secret_value(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"OAuth config not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"OAuth config is empty: {path}")
    if path.suffix in {".json"} or text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OAuth config must be valid JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"OAuth config must be a JSON object: {path}")
        return json.dumps(payload, sort_keys=True)
    return text


def _register_provider_credential(
    *,
    provider: str,
    tenant_id: str,
    api_key: str,
    oauth_json: Path,
    base_url: str,
    credential_id: str | None,
) -> dict[str, Any]:
    if provider not in PROVIDER_REGISTRATIONS:
        supported = ", ".join(sorted(PROVIDER_REGISTRATIONS))
        raise ValueError(f"unsupported provider {provider!r}; supported: {supported}")

    secret_value = _load_secret_value(oauth_json)
    registration = dict(PROVIDER_REGISTRATIONS[provider])
    if credential_id:
        registration["credential_id"] = credential_id.strip()

    payload = {
        **registration,
        "secret_value": secret_value,
    }
    url = f"{base_url.rstrip('/')}/v1/account/provider-credentials"
    headers = {
        "X-Tenant-Id": tenant_id.strip(),
        "X-Api-Key": api_key.strip(),
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"register failed HTTP {response.status_code}: {response.text[:500]}")
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("register response must be a JSON object")
    return body


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge local OAuth token files to Ajenda tenant Credentials API",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser(
        "register",
        help="POST provider credential using secret_value from a local OAuth JSON/YAML file",
    )
    register.add_argument(
        "provider",
        choices=sorted(PROVIDER_REGISTRATIONS),
        help="Provider integration to register",
    )
    register.add_argument("--tenant-id", required=True, help="Tenant UUID")
    register.add_argument("--api-key", required=True, help="Operational API key (key_id.secret)")
    register.add_argument(
        "--oauth-json",
        type=Path,
        help="Path to OAuth token file (default: ~/.ajenda/<provider>-oauth.json)",
    )
    register.add_argument(
        "--credential-id",
        help="Override default credential_id for the provider",
    )
    register.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Ajenda API base URL (default: http://127.0.0.1:8000)",
    )
    return parser.parse_args()


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    args = _parse_args()
    if args.command != "register":
        print(f"unsupported command: {args.command}", file=sys.stderr)
        return 2

    oauth_path = args.oauth_json or DEFAULT_OAUTH_PATHS[args.provider]
    try:
        body = _register_provider_credential(
            provider=args.provider,
            tenant_id=args.tenant_id,
            api_key=args.api_key,
            oauth_json=oauth_path.expanduser(),
            base_url=args.base_url,
            credential_id=args.credential_id,
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    credential = body.get("credential")
    if isinstance(credential, dict):
        print(f"registered credential_id={credential.get('credential_id')}")
        print(f"tenant_id={credential.get('tenant_id')}")
        hosts = credential.get("trusted_destination_hosts")
        if isinstance(hosts, list) and hosts:
            print(f"trusted_destination_hosts={','.join(str(item) for item in hosts)}")
    else:
        print(json.dumps(body, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())