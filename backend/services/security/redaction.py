from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
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


def _normalize_exact_key(key: object) -> str:
    return str(key).strip().lower()


def _normalize_fragment_key(key: object) -> str:
    return _normalize_exact_key(key).replace("-", "_")


def _normalized_additional_keys(additional_sensitive_keys: Collection[str] | None) -> set[str]:
    return {_normalize_exact_key(key) for key in additional_sensitive_keys or () if str(key).strip()}


def is_sensitive_key(key: object, *, additional_sensitive_keys: Collection[str] | None = None) -> bool:
    return _is_sensitive_key(key, additional_sensitive_keys=_normalized_additional_keys(additional_sensitive_keys))


def redact_sensitive_data(value: Any, *, additional_sensitive_keys: Collection[str] | None = None) -> Any:
    return _redact_sensitive_data(
        value, additional_sensitive_keys=_normalized_additional_keys(additional_sensitive_keys)
    )


def _redact_sensitive_data(value: Any, *, additional_sensitive_keys: set[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED_VALUE
            if _is_sensitive_key(key, additional_sensitive_keys=additional_sensitive_keys)
            else _redact_sensitive_data(item, additional_sensitive_keys=additional_sensitive_keys)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_data(item, additional_sensitive_keys=additional_sensitive_keys) for item in value]
    if isinstance(value, tuple):
        return tuple(
            _redact_sensitive_data(item, additional_sensitive_keys=additional_sensitive_keys) for item in value
        )
    return value


def _is_sensitive_key(key: object, *, additional_sensitive_keys: set[str]) -> bool:
    exact_key = _normalize_exact_key(key)
    if exact_key in additional_sensitive_keys:
        return True
    normalized = _normalize_fragment_key(key)
    if normalized == "side_effect_authorization":
        return False
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(is_sensitive_key(key) or contains_sensitive_key(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_sensitive_key(item) for item in value)
    return False
