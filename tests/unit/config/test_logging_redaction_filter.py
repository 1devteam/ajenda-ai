from __future__ import annotations

from backend.app.logging import RedactionFilter
from backend.services.security.redaction import REDACTED_VALUE


def test_redaction_filter_honors_configured_keys_recursively() -> None:
    payload = {
        "cookie": "cookie-value",
        "Set-Cookie": "set-cookie-value",
        "nested": [{"custom_session": "custom-value"}, {"value": "visible"}],
    }
    redactor = RedactionFilter({"cookie", "set-cookie", "custom_session"})

    redacted = redactor._redact_mapping(payload)

    assert redacted == {
        "cookie": REDACTED_VALUE,
        "Set-Cookie": REDACTED_VALUE,
        "nested": [{"custom_session": REDACTED_VALUE}, {"value": "visible"}],
    }
