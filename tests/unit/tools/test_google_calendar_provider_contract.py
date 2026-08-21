from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.tools.credential_resolver import CredentialResolutionError, ResolvedExternalCredential
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


class _Resolver:
    def resolve(self, reference):
        return ResolvedExternalCredential(reference=reference, secret_value="token")


def test_google_calendar_provider_reads_and_creates_through_network_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GoogleCalendarProvider(credential=_credential(), resolver=_Resolver())
    responses = iter([SimpleNamespace(status_code=200, body_text='{"items":[{"id":"event-1"}]}')])

    class _Authority:
        def request(self, **kwargs):
            return SimpleNamespace(original_url=kwargs["url"]), next(responses)

    monkeypatch.setattr(
        "backend.services.tools.google_calendar_provider.get_default_network_egress_authority",
        lambda: _Authority(),
    )

    assert provider.read_events(tenant_id="tenant-1", calendar_id="primary") == [{"id": "event-1"}]


def test_google_calendar_provider_rejects_ungoverned_external_create() -> None:
    provider = GoogleCalendarProvider(credential=_credential(), resolver=_Resolver())

    with pytest.raises(CredentialResolutionError, match=r"governed tool\.invoke authorization path"):
        provider.create_event(tenant_id="tenant-1", calendar_id="primary", event={"summary": "Demo"})


def test_google_calendar_provider_requires_resolvable_credential() -> None:
    provider = GoogleCalendarProvider(credential=_credential())

    with pytest.raises(Exception, match="requires a deployment credential resolver"):
        provider.read_events(tenant_id="tenant-1", calendar_id="primary")


def test_required_google_calendar_scopes_are_minimal_by_operation() -> None:
    assert required_google_calendar_scopes(write=False) == (GOOGLE_CALENDAR_READ_SCOPE,)
    assert required_google_calendar_scopes(write=True) == (GOOGLE_CALENDAR_EVENTS_SCOPE,)
    # Product connector default is write/events consent.
    assert required_google_calendar_scopes() == (GOOGLE_CALENDAR_EVENTS_SCOPE,)
