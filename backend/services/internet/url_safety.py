"""Reject credential-bearing URLs for public-internet actions."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

CREDENTIAL_LIKE_VALUE_FRAGMENTS = (
    "bearer ",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token=",
    "session=",
    "secret",
    "password",
    "private_key",
    "client_secret",
)
SENSITIVE_URL_QUERY_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer",
    "token",
    "session",
    "cookie",
    "credential",
    "password",
    "secret",
    "private_key",
    "client_secret",
)


def _value_contains_credential_material(value: str) -> bool:
    normalized = value.lower()
    return any(fragment in normalized for fragment in CREDENTIAL_LIKE_VALUE_FRAGMENTS)


def _url_query_key_is_sensitive(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(fragment in normalized for fragment in SENSITIVE_URL_QUERY_KEY_FRAGMENTS)


def reject_credentialed_url(url: str, *, action_name: str) -> str:
    """Return stripped URL or raise ValueError if credentials are embedded."""

    raw = url.strip()
    if not raw:
        raise ValueError(f"{action_name} URL is required")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.username or parsed.password:
        raise ValueError(f"{action_name} URL must not include userinfo credentials")
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if _url_query_key_is_sensitive(key):
            raise ValueError(f"{action_name} URL query must not include credential parameters")
        if _value_contains_credential_material(item):
            raise ValueError(f"{action_name} URL query must not include credential-like values")
    return raw
