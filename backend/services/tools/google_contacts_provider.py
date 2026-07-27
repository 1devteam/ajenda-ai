"""Google Contacts (People API) provider contract and OAuth scopes.

Connector OAuth only — identity login must never request these scopes.
"""

from __future__ import annotations

# Product connector consent matches Google Cloud OAuth client scopes in use.
GOOGLE_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts"
GOOGLE_CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
GOOGLE_CONTACTS_OTHER_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.other.readonly"
GOOGLE_PEOPLE_API_HOST = "people.googleapis.com"


def required_google_contacts_scopes(*, write: bool = True) -> tuple[str, ...]:
    """Scopes requested for Contacts connector OAuth.

    Product default is full ``contacts`` plus ``contacts.other.readonly`` so
    auto-saved "Other contacts" are available, matching the Ajenda Google
    OAuth client consent configuration.
    """

    if write:
        return (GOOGLE_CONTACTS_SCOPE, GOOGLE_CONTACTS_OTHER_READONLY_SCOPE)
    return (GOOGLE_CONTACTS_READONLY_SCOPE, GOOGLE_CONTACTS_OTHER_READONLY_SCOPE)


def recognized_google_contacts_scopes() -> tuple[str, ...]:
    """Scopes that identify a stored secret as a contacts OAuth bundle."""

    return (
        GOOGLE_CONTACTS_SCOPE,
        GOOGLE_CONTACTS_READONLY_SCOPE,
        GOOGLE_CONTACTS_OTHER_READONLY_SCOPE,
    )
