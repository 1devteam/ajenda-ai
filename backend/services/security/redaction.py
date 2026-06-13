from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_VALUE = "***REDACTED***"
SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "bearer",
        "password",
        "secret",
        "private_key",
        "client_secret",
        "webhook_secret",
        "plaintext_secret",
        "secret_value",
    }
)


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized == "side_effect_authorization":
        return False
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED_VALUE if is_sensitive_key(key) else redact_sensitive_data(item) for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(is_sensitive_key(key) or contains_sensitive_key(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_sensitive_key(item) for item in value)
    return False
