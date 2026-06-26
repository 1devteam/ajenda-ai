"""Gmail provider adapter contract and documented OAuth scopes."""

from __future__ import annotations

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

GMAIL_API_HOST = "gmail.googleapis.com"
DEFAULT_GMAIL_CLI_REDIRECT_URI = "http://127.0.0.1:8765/oauth2/callback"
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


def required_gmail_scopes(*, read: bool = True, send: bool = True) -> tuple[str, ...]:
    """Return the minimum documented Gmail API scopes for Ajenda email actions."""

    scopes: list[str] = []
    if read:
        scopes.append(GMAIL_READONLY_SCOPE)
    if send:
        scopes.append(GMAIL_SEND_SCOPE)
    return tuple(scopes)
