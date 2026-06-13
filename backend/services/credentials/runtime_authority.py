from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.services.security.redaction import contains_sensitive_key
from backend.services.tools.schemas import (
    CredentialReference,
    RuntimeCredentialMaterial,
    SideEffectClass,
    ToolInvocation,
)


class CredentialRuntimeAuthorityError(ValueError):
    """Deterministic public denial for credential runtime boundary failures."""


@dataclass(frozen=True, slots=True)
class CredentialRequirement:
    provider: str
    credential_type: str
    allowed_side_effect_classes: tuple[SideEffectClass, ...] = field(default_factory=tuple)


class CredentialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=120)
    credential_type: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    revoked: bool = False
    deleted: bool = False
    allowed_actions: tuple[str, ...] = ()
    allowed_side_effect_classes: tuple[SideEffectClass, ...] = ()
    trusted_destination_hosts: tuple[str, ...] = ()
    secret_value: str = Field(min_length=1, repr=False, exclude=True)

    @field_validator("trusted_destination_hosts")
    @classmethod
    def normalize_trusted_destination_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for host in value:
            normalized_host = host.strip().lower().rstrip(".")
            if not normalized_host:
                raise ValueError("trusted_destination_hosts must contain non-empty hostnames")
            if "://" in normalized_host or "/" in normalized_host or "@" in normalized_host:
                raise ValueError("trusted_destination_hosts must contain hostnames only")
            normalized.append(normalized_host)
        return tuple(dict.fromkeys(normalized))


class CredentialRuntimeRepository(Protocol):
    def get_visible_for_tenant(self, *, tenant_id: str, credential_id: str) -> CredentialRecord | None:
        """Return tenant-owned or tenant-visible credential metadata plus runtime secret material."""


class EmptyCredentialRuntimeRepository:
    def get_visible_for_tenant(self, *, tenant_id: str, credential_id: str) -> CredentialRecord | None:
        return None


class InMemoryCredentialRuntimeRepository:
    def __init__(self, records: list[CredentialRecord] | None = None) -> None:
        self._records = {(record.tenant_id, record.credential_id): record for record in records or []}

    def add(self, record: CredentialRecord) -> None:
        self._records[(record.tenant_id, record.credential_id)] = record

    def get_visible_for_tenant(self, *, tenant_id: str, credential_id: str) -> CredentialRecord | None:
        return self._records.get((tenant_id, credential_id))


class CredentialRuntimeAuthority:
    """Fail-closed authority boundary for runtime-only credential resolution."""

    def __init__(self, *, repository: CredentialRuntimeRepository | None = None) -> None:
        self._repository = repository or EmptyCredentialRuntimeRepository()

    def reject_raw_secret_metadata(self, *, metadata: object) -> None:
        if contains_sensitive_key(metadata):
            raise CredentialRuntimeAuthorityError("raw secret material is not allowed in task metadata")

    def reject_raw_secret_invocation(self, *, invocation: ToolInvocation) -> None:
        if contains_sensitive_key(invocation.input):
            raise CredentialRuntimeAuthorityError("raw secret material is not allowed in tool invocation input")

    def resolve_for_action(
        self,
        *,
        tenant_id: str,
        invocation: ToolInvocation,
        metadata_reference: object,
        action_name: str,
        provider: str,
        side_effect_class: SideEffectClass,
        requirement: CredentialRequirement | None,
    ) -> RuntimeCredentialMaterial | None:
        self.reject_raw_secret_invocation(invocation=invocation)
        raw_reference = metadata_reference if metadata_reference is not None else invocation.credential_reference
        if raw_reference is None:
            if requirement is None:
                return None
            raise CredentialRuntimeAuthorityError("credential_reference is required")
        reference = CredentialReference.model_validate(raw_reference)
        if requirement is not None:
            if reference.provider != requirement.provider or reference.credential_type != requirement.credential_type:
                raise CredentialRuntimeAuthorityError(
                    "credential_reference is not compatible with action provider/type"
                )
            if (
                requirement.allowed_side_effect_classes
                and side_effect_class not in requirement.allowed_side_effect_classes
            ):
                raise CredentialRuntimeAuthorityError("credential_reference is not allowed for side-effect class")
        if reference.provider != provider:
            raise CredentialRuntimeAuthorityError("credential_reference provider does not match action provider")
        record = self._repository.get_visible_for_tenant(tenant_id=tenant_id, credential_id=reference.credential_id)
        if record is None:
            raise CredentialRuntimeAuthorityError("credential_reference is not visible for tenant")
        self._validate_record(
            record=record,
            reference=reference,
            action_name=action_name,
            side_effect_class=side_effect_class,
        )
        return RuntimeCredentialMaterial(
            reference=reference,
            secret_value=record.secret_value,
            trusted_destination_hosts=record.trusted_destination_hosts,
        )

    def _validate_record(
        self,
        *,
        record: CredentialRecord,
        reference: CredentialReference,
        action_name: str,
        side_effect_class: SideEffectClass,
    ) -> None:
        if not record.enabled:
            raise CredentialRuntimeAuthorityError("credential_reference is disabled")
        if record.revoked:
            raise CredentialRuntimeAuthorityError("credential_reference is revoked")
        if record.deleted:
            raise CredentialRuntimeAuthorityError("credential_reference is deleted")
        if record.provider != reference.provider or record.credential_type != reference.credential_type:
            raise CredentialRuntimeAuthorityError("credential_reference is not compatible with stored credential")
        if record.allowed_actions and action_name not in record.allowed_actions:
            raise CredentialRuntimeAuthorityError("credential_reference is not allowed for action")
        if record.allowed_side_effect_classes and side_effect_class not in record.allowed_side_effect_classes:
            raise CredentialRuntimeAuthorityError("credential_reference is not allowed for side-effect class")
