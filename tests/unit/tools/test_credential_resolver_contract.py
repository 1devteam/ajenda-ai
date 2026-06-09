from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.tools.credential_resolver import ResolvedExternalCredential, UnresolvedCredentialResolver
from backend.services.tools.external_credentials import (
    CredentialReferenceKind,
    ExternalCredentialReference,
    ExternalProviderName,
)


def _reference() -> ExternalCredentialReference:
    return ExternalCredentialReference(
        provider=ExternalProviderName.GOOGLE_CALENDAR,
        tenant_id="tenant-1",
        kind=CredentialReferenceKind.SECRET_MANAGER,
        reference="projects/ajenda/secrets/google-calendar/tenant-1",
        scopes=("https://www.googleapis.com/auth/calendar.events",),
        subject="calendar-user@example.com",
    )


def test_resolved_external_credential_keeps_secret_out_of_repr() -> None:
    resolved = ResolvedExternalCredential(
        reference=_reference(),
        secret_value="runtime-secret-value",
        expires_at="2026-06-08T10:00:00Z",
        issued_subject="calendar-user@example.com",
    )

    assert resolved.secret_value == "runtime-secret-value"
    assert "runtime-secret-value" not in repr(resolved)


def test_resolved_external_credential_rejects_empty_secret() -> None:
    with pytest.raises(ValidationError):
        ResolvedExternalCredential(reference=_reference(), secret_value="")


def test_resolved_external_credential_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ResolvedExternalCredential.model_validate(
            {
                "reference": _reference().model_dump(mode="json"),
                "secret_value": "runtime-secret-value",
                "plaintext_secret": "not-allowed",
            }
        )


def test_unresolved_credential_resolver_fails_closed() -> None:
    resolver = UnresolvedCredentialResolver()

    with pytest.raises(NotImplementedError, match="credential resolution is not implemented"):
        resolver.resolve(_reference())
