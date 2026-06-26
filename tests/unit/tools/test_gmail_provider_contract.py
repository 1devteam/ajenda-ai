from __future__ import annotations

from backend.services.tools.gmail_provider import (
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    required_gmail_scopes,
)


def test_required_gmail_scopes_are_minimal_by_operation() -> None:
    assert required_gmail_scopes(read=True, send=False) == (GMAIL_READONLY_SCOPE,)
    assert required_gmail_scopes(read=False, send=True) == (GMAIL_SEND_SCOPE,)
    assert required_gmail_scopes() == (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE)
