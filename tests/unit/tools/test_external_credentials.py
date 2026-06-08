from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.tools.external_credentials import (
    CredentialReferenceKind,
    ExternalCredentialReference,
    ExternalProviderName,
)


def test_external_credential_reference_is_tenant_scoped_non_secret_pointer() -> None:
    reference = ExternalCredentialReference(
        provider=ExternalProviderName.GOOGLE_CALENDAR,
        tenant_id=" tenant-1 ",
        kind=CredentialReferenceKind.SECRET_MANAGER,
        reference=" projects/ajenda/secrets/google-calendar/tenant-1 ",
        scopes=(" https://www.googleapis.com/auth/calendar.events ",),
        subject=" user@example.com ",
    )

    assert reference.tenant_id == "tenant-1"
    assert reference.reference == "projects/ajenda/secrets/google-calendar/tenant-1"
    assert reference.scopes == ("https://www.googleapis.com/auth/calendar.events",)
    assert reference.subject == "user@example.com"
    assert reference.plaintext_secret is None


def test_external_credential_reference_rejects_plaintext_secret() -> None:
    with pytest.raises(ValidationError):
        ExternalCredentialReference.model_validate(
            {
                "provider": "google_calendar",
                "tenant_id": "tenant-1",
                "kind": "secret_manager",
                "reference": "secret-ref",
                "plaintext_secret": "do-not-store-this",
            }
        )


def test_external_credential_reference_rejects_blank_scope() -> None:
    with pytest.raises(ValidationError, match="scope entries"):
        ExternalCredentialReference(
            provider=ExternalProviderName.GOOGLE_CALENDAR,
            tenant_id="tenant-1",
            kind=CredentialReferenceKind.SECRET_MANAGER,
            reference="secret-ref",
            scopes=("calendar", "   "),
        )


def test_external_credential_reference_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ExternalCredentialReference.model_validate(
            {
                "provider": "github",
                "tenant_id": "tenant-1",
                "kind": "secret_manager",
                "reference": "secret-ref",
                "token": "not-allowed",
            }
        )
