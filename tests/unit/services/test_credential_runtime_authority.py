from __future__ import annotations

import pytest

from backend.services.credentials.runtime_authority import (
    CredentialRecord,
    CredentialRequirement,
    CredentialRuntimeAuthority,
    CredentialRuntimeAuthorityError,
    InMemoryCredentialRuntimeRepository,
)
from backend.services.tools.schemas import SideEffectClass, ToolInvocation


def _authority(record: CredentialRecord | None = None) -> CredentialRuntimeAuthority:
    repo = InMemoryCredentialRuntimeRepository([record] if record else [])
    return CredentialRuntimeAuthority(repository=repo)


def _record(**overrides: object) -> CredentialRecord:
    values = {
        "credential_id": "cred-1",
        "tenant_id": "tenant-a",
        "provider": "local_records",
        "credential_type": "api_key",
        "allowed_actions": ("record.search",),
        "allowed_side_effect_classes": (SideEffectClass.NONE,),
        "secret_value": "sk-test-secret-value",
    }
    values.update(overrides)
    return CredentialRecord.model_validate(values)


def _reference(**overrides: object) -> dict[str, object]:
    values = {"schema_version": 1, "credential_id": "cred-1", "provider": "local_records", "credential_type": "api_key"}
    values.update(overrides)
    return values


def _resolve(authority: CredentialRuntimeAuthority, **overrides: object):
    return authority.resolve_for_action(
        tenant_id=str(overrides.pop("tenant_id", "tenant-a")),
        invocation=ToolInvocation(action="record.search", input={}),
        metadata_reference=overrides.pop("metadata_reference", _reference()),
        action_name=str(overrides.pop("action_name", "record.search")),
        provider=str(overrides.pop("provider", "local_records")),
        side_effect_class=overrides.pop("side_effect_class", SideEffectClass.NONE),
        requirement=overrides.pop(
            "requirement",
            CredentialRequirement(provider="local_records", credential_type="api_key"),
        ),
    )


def test_valid_credential_reference_resolves_runtime_secret_without_serializing_secret() -> None:
    resolved = _resolve(_authority(_record()))

    assert resolved.reference.credential_id == "cred-1"
    assert resolved.model_dump(mode="json") == {
        "reference": {
            "schema_version": 1,
            "credential_id": "cred-1",
            "provider": "local_records",
            "credential_type": "api_key",
        }
    }
    assert "sk-test-secret-value" not in repr(resolved)


@pytest.mark.parametrize(
    ("record_overrides", "message"),
    [
        ({"enabled": False}, "disabled"),
        ({"revoked": True}, "revoked"),
        ({"deleted": True}, "deleted"),
    ],
)
def test_disabled_revoked_or_deleted_credentials_fail_closed(record_overrides: dict[str, object], message: str) -> None:
    with pytest.raises(CredentialRuntimeAuthorityError, match=message):
        _resolve(_authority(_record(**record_overrides)))


def test_unknown_and_cross_tenant_credentials_fail_closed() -> None:
    with pytest.raises(CredentialRuntimeAuthorityError, match="not visible"):
        _resolve(_authority())
    with pytest.raises(CredentialRuntimeAuthorityError, match="not visible"):
        _resolve(_authority(_record(tenant_id="tenant-b")))


def test_provider_type_action_and_side_effect_compatibility_fail_closed() -> None:
    with pytest.raises(CredentialRuntimeAuthorityError, match="provider/type"):
        _resolve(_authority(_record()), metadata_reference=_reference(provider="other"))
    with pytest.raises(CredentialRuntimeAuthorityError, match="stored credential"):
        _resolve(_authority(_record(provider="other")), requirement=None)
    with pytest.raises(CredentialRuntimeAuthorityError, match="action"):
        _resolve(_authority(_record(allowed_actions=("record.read",))))
    with pytest.raises(CredentialRuntimeAuthorityError, match="side-effect"):
        _resolve(_authority(_record(allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,))))


def test_allowed_credential_types_accepts_smtp_and_platform_master() -> None:
    requirement = CredentialRequirement(
        provider="external_email",
        credential_type="api_key",
        allowed_credential_types=("api_key", "smtp", "platform_master"),
        allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,),
    )
    for cred_type in ("smtp", "platform_master", "api_key"):
        resolved = _resolve(
            _authority(
                _record(
                    provider="external_email",
                    credential_type=cred_type,
                    allowed_actions=("gtm.email_send",),
                    allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,),
                )
            ),
            action_name="gtm.email_send",
            provider="external_email",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            requirement=requirement,
            metadata_reference=_reference(
                provider="external_email",
                credential_type=cred_type,
            ),
        )
        assert resolved is not None
        assert resolved.reference.credential_type == cred_type

    with pytest.raises(CredentialRuntimeAuthorityError, match="provider/type"):
        _resolve(
            _authority(
                _record(
                    provider="external_email",
                    credential_type="oauth_token",
                    allowed_actions=("gtm.email_send",),
                    allowed_side_effect_classes=(SideEffectClass.EXTERNAL_SEND,),
                )
            ),
            action_name="gtm.email_send",
            provider="external_email",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            requirement=requirement,
            metadata_reference=_reference(provider="external_email", credential_type="oauth_token"),
        )


def test_missing_required_reference_fails_closed_but_optional_reference_is_absent() -> None:
    with pytest.raises(CredentialRuntimeAuthorityError, match="credential_reference is required"):
        _resolve(_authority(_record()), metadata_reference=None)
    assert _resolve(_authority(_record()), metadata_reference=None, requirement=None) is None


def test_raw_secret_keys_are_rejected_from_metadata_and_invocation_input() -> None:
    authority = _authority(_record())
    with pytest.raises(CredentialRuntimeAuthorityError, match="task metadata"):
        authority.reject_raw_secret_metadata(metadata={"nested": [{"access_token": "secret"}]})
    with pytest.raises(CredentialRuntimeAuthorityError, match="tool invocation input"):
        authority.resolve_for_action(
            tenant_id="tenant-a",
            invocation=ToolInvocation(action="record.search", input={"headers": {"Authorization": "Bearer x"}}),
            metadata_reference=_reference(),
            action_name="record.search",
            provider="local_records",
            side_effect_class=SideEffectClass.NONE,
            requirement=CredentialRequirement(provider="local_records", credential_type="api_key"),
        )
