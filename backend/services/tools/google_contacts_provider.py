"""Google Contacts (People API) provider contract and OAuth scopes.

Connector OAuth only — identity login must never request these scopes.
"""

from __future__ import annotations

GOOGLE_CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
GOOGLE_PEOPLE_API_HOST = "people.googleapis.com"


def required_google_contacts_scopes(*, write: bool = False) -> tuple[str, ...]:
    """Return the minimum documented scopes for Google Contacts operations."""

    if write:
        # Write scope reserved for a future governed ability; product connect is read-only.
        return ("https://www.googleapis.com/auth/contacts",)
    return (GOOGLE_CONTACTS_READONLY_SCOPE,)
