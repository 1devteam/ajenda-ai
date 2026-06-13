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


def redact_sensitive_data(
    value: Any,
    *,
    additional_sensitive_keys: Collection[str] | None = None,
    additional_sensitive_values: Collection[str] | None = None,
) -> Any:
    return _redact_sensitive_data(
        value,
        additional_sensitive_keys=_normalized_additional_keys(additional_sensitive_keys),
        additional_sensitive_values=_normalized_sensitive_values(additional_sensitive_values),
    )


def _normalized_sensitive_values(additional_sensitive_values: Collection[str] | None) -> tuple[str, ...]:
    return tuple(sorted((value for value in additional_sensitive_values or () if value), key=len, reverse=True))


def _redact_sensitive_data(
    value: Any, *, additional_sensitive_keys: set[str], additional_sensitive_values: tuple[str, ...]
) -> Any:
    if isinstance(value, Mapping):
        redacted_mapping: dict[Any, Any] = {}
        for key, item in value.items():
            redacted_key = _redact_sensitive_string(key, sensitive_values=additional_sensitive_values)
            if _is_sensitive_key(key, additional_sensitive_keys=additional_sensitive_keys):
                redacted_mapping[redacted_key] = REDACTED_VALUE
            else:
                redacted_mapping[redacted_key] = _redact_sensitive_data(
                    item,
                    additional_sensitive_keys=additional_sensitive_keys,
                    additional_sensitive_values=additional_sensitive_values,
                )
        return redacted_mapping
    if isinstance(value, list):
        return [
            _redact_sensitive_data(
                item,
                additional_sensitive_keys=additional_sensitive_keys,
                additional_sensitive_values=additional_sensitive_values,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_sensitive_data(
                item,
                additional_sensitive_keys=additional_sensitive_keys,
                additional_sensitive_values=additional_sensitive_values,
            )
            for item in value
        )
    return _redact_sensitive_string(value, sensitive_values=additional_sensitive_values)


def _redact_sensitive_string(value: Any, *, sensitive_values: tuple[str, ...]) -> Any:
    if not isinstance(value, str):
        return value
    redacted = value
    for sensitive_value in sensitive_values:
        redacted = redacted.replace(sensitive_value, REDACTED_VALUE)
    return redacted


def contains_sensitive_value(value: Any, sensitive_values: Collection[str]) -> bool:
    normalized_sensitive_values = _normalized_sensitive_values(sensitive_values)
    if not normalized_sensitive_values:
        return False
    if isinstance(value, Mapping):
        return any(
            contains_sensitive_value(key, normalized_sensitive_values)
            or contains_sensitive_value(item, normalized_sensitive_values)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_sensitive_value(item, normalized_sensitive_values) for item in value)
    if isinstance(value, str):
        return any(sensitive_value in value for sensitive_value in normalized_sensitive_values)
    return False


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
