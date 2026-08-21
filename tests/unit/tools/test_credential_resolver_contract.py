from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.tools.credential_resolver import (
    CredentialResolutionError,
    EnvironmentCredentialResolver,
    ResolvedExternalCredential,
)
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


def test_environment_credential_resolver_resolves_only_explicit_environment_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference = _reference().model_copy(
        update={"kind": CredentialReferenceKind.ENV_VAR, "reference": "AJENDA_TEST_SECRET"}
    )
    monkeypatch.setenv("AJENDA_TEST_SECRET", "runtime-secret-value")

    resolved = EnvironmentCredentialResolver().resolve(reference)

    assert resolved.secret_value == "runtime-secret-value"
    assert resolved.issued_subject == "calendar-user@example.com"


def test_environment_credential_resolver_rejects_unwired_store_kind() -> None:
    with pytest.raises(CredentialResolutionError, match="requires a deployment credential resolver"):
        EnvironmentCredentialResolver().resolve(_reference())


def test_environment_credential_resolver_fails_closed_when_variable_missing() -> None:
    reference = _reference().model_copy(
        update={"kind": CredentialReferenceKind.ENV_VAR, "reference": "AJENDA_MISSING_SECRET"}
    )
    with pytest.raises(CredentialResolutionError, match="is not set"):
        EnvironmentCredentialResolver().resolve(reference)
