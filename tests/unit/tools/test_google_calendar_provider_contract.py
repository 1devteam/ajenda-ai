from __future__ import annotations

import pytest

from backend.services.tools.external_credentials import (
    CredentialReferenceKind,
    ExternalCredentialReference,
    ExternalProviderName,
)
from backend.services.tools.google_calendar_provider import (
    GOOGLE_CALENDAR_EVENTS_SCOPE,
    GOOGLE_CALENDAR_READ_SCOPE,
    GoogleCalendarProvider,
    required_google_calendar_scopes,
)


def _credential(
    *,
    provider: ExternalProviderName = ExternalProviderName.GOOGLE_CALENDAR,
    tenant_id: str = "tenant-1",
) -> ExternalCredentialReference:
    return ExternalCredentialReference(
        provider=provider,
        tenant_id=tenant_id,
        kind=CredentialReferenceKind.SECRET_MANAGER,
        reference=f"projects/ajenda/secrets/{provider.value}/{tenant_id}",
        scopes=(GOOGLE_CALENDAR_EVENTS_SCOPE,),
        subject="calendar-user@example.com",
    )


def test_google_calendar_provider_requires_google_calendar_credentials() -> None:
    with pytest.raises(ValueError, match="google_calendar credentials"):
        GoogleCalendarProvider(credential=_credential(provider=ExternalProviderName.GITHUB))


def test_google_calendar_provider_keeps_non_secret_credential_reference() -> None:
    credential = _credential()

    provider = GoogleCalendarProvider(credential=credential)

    assert provider.credential == credential
    assert provider.credential.plaintext_secret is None


def test_google_calendar_provider_rejects_cross_tenant_calls_before_external_work() -> None:
    provider = GoogleCalendarProvider(credential=_credential(tenant_id="tenant-1"))

    with pytest.raises(ValueError, match="tenant_id"):
        provider.read_events(tenant_id="tenant-2", calendar_id="primary")


def test_google_calendar_provider_operations_are_explicitly_deferred() -> None:
    provider = GoogleCalendarProvider(credential=_credential())

    with pytest.raises(NotImplementedError, match="read provider"):
        provider.read_events(tenant_id="tenant-1", calendar_id="primary")

    with pytest.raises(NotImplementedError, match="create provider"):
        provider.create_event(
            tenant_id="tenant-1",
            calendar_id="primary",
            event={
                "title": "Demo",
                "start": "2026-06-08T10:00:00Z",
                "end": "2026-06-08T10:30:00Z",
            },
        )


def test_required_google_calendar_scopes_are_minimal_by_operation() -> None:
    assert required_google_calendar_scopes(write=False) == (GOOGLE_CALENDAR_READ_SCOPE,)
    assert required_google_calendar_scopes(write=True) == (GOOGLE_CALENDAR_EVENTS_SCOPE,)
