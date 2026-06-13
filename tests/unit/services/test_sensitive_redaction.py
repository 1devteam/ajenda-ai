from __future__ import annotations

from backend.services.security.redaction import (
    REDACTED_VALUE,
    contains_sensitive_key,
    contains_sensitive_value,
    redact_sensitive_data,
)


def test_redaction_is_recursive_and_covers_common_sensitive_keys() -> None:
    payload = {
        "api_key": "api-key-value",
        "token": "token-value",
        "access_token": "access-token-value",
        "refresh_token": "refresh-token-value",
        "authorization": "Bearer auth-value",
        "bearer": "bearer-value",
        "password": "password-value",
        "secret": "secret-value",
        "private_key": "private-key-value",
        "client_secret": "client-secret-value",
        "webhook_secret": "webhook-secret-value",
        "safe": [{"nested_token": "nested-token-value"}, {"value": "visible"}],
    }

    redacted = redact_sensitive_data(payload)

    assert redacted == {
        "api_key": REDACTED_VALUE,
        "token": REDACTED_VALUE,
        "access_token": REDACTED_VALUE,
        "refresh_token": REDACTED_VALUE,
        "authorization": REDACTED_VALUE,
        "bearer": REDACTED_VALUE,
        "password": REDACTED_VALUE,
        "secret": REDACTED_VALUE,
        "private_key": REDACTED_VALUE,
        "client_secret": REDACTED_VALUE,
        "webhook_secret": REDACTED_VALUE,
        "safe": [{"nested_token": REDACTED_VALUE}, {"value": "visible"}],
    }
    assert contains_sensitive_key(payload) is True
    assert contains_sensitive_key({"safe": [{"value": "visible"}]}) is False
    assert (
        contains_sensitive_key({"execution_constraints": {"side_effect_authorization": {"approved_by": "qa"}}}) is False
    )


def test_redaction_accepts_configured_exact_keys_recursively() -> None:
    payload = {
        "cookie": "cookie-value",
        "Set-Cookie": "set-cookie-value",
        "nested": [{"session_id": "session-value"}, {"value": "visible"}],
    }

    redacted = redact_sensitive_data(payload, additional_sensitive_keys={"cookie", "set-cookie", "session_id"})

    assert redacted == {
        "cookie": REDACTED_VALUE,
        "Set-Cookie": REDACTED_VALUE,
        "nested": [{"session_id": REDACTED_VALUE}, {"value": "visible"}],
    }


def test_redaction_accepts_configured_sensitive_values_recursively() -> None:
    payload = {
        "summary": "neutral field leaked sk-runtime-12345",
        "nested": [{"message": "prefix sk-runtime-12345 suffix"}, "sk-runtime-12345"],
        "key-sk-runtime-12345": "value under credential-bearing key",
        "safe": "visible",
    }

    assert contains_sensitive_value(payload, {"sk-runtime-12345"}) is True

    redacted = redact_sensitive_data(payload, additional_sensitive_values={"sk-runtime-12345"})

    assert redacted == {
        "summary": "neutral field leaked ***REDACTED***",
        "nested": [{"message": "prefix ***REDACTED*** suffix"}, "***REDACTED***"],
        "key-***REDACTED***": "value under credential-bearing key",
        "safe": "visible",
    }
    assert contains_sensitive_value(redacted, {"sk-runtime-12345"}) is False
