"""Credential resolver contract for external provider adapters.

This module defines the boundary for resolving ExternalCredentialReference values
into runtime-only credential material. It does not implement secret storage,
OAuth refresh, provider API clients, or persistent credential access.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.services.tools.external_credentials import ExternalCredentialReference


class ResolvedExternalCredential(BaseModel):
    """Runtime-only resolved credential material.

    The secret value is excluded from repr so it is not exposed by normal debug
    formatting. Provider adapters must not persist or log this value.
    """

    model_config = ConfigDict(extra="forbid")

    reference: ExternalCredentialReference
    secret_value: str = Field(min_length=1, repr=False)
    expires_at: str | None = Field(default=None, max_length=80)
    issued_subject: str | None = Field(default=None, max_length=240)


class CredentialResolver(Protocol):
    """Boundary for resolving credential references at runtime."""

    def resolve(self, reference: ExternalCredentialReference) -> ResolvedExternalCredential:
        """Resolve a credential reference into runtime-only credential material."""


class UnresolvedCredentialResolver:
    """Fail-closed resolver used until real secret resolution is implemented."""

    def resolve(self, reference: ExternalCredentialReference) -> ResolvedExternalCredential:
        """Always fail closed because no live credential resolver is wired."""

        raise NotImplementedError(f"credential resolution is not implemented for {reference.provider.value}")
