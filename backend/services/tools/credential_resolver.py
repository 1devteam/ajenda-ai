"""Credential resolver contract for external provider adapters.

This module defines the boundary for resolving ExternalCredentialReference values
into runtime-only credential material. It does not implement secret storage,
OAuth refresh, provider API clients, or persistent credential access.
"""

from __future__ import annotations

import os
import re
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


class CredentialResolutionError(RuntimeError):
    """A credential reference could not be resolved without exposing secrets."""


class CredentialResolver(Protocol):
    """Boundary for resolving credential references at runtime."""

    def resolve(self, reference: ExternalCredentialReference) -> ResolvedExternalCredential:
        """Resolve a credential reference into runtime-only credential material."""


class EnvironmentCredentialResolver:
    """Resolve explicitly-scoped environment variable credential references.

    Secret-manager, Kubernetes, and OAuth-token-store references are rejected
    here rather than guessed. Deployments that use those stores must provide a
    resolver implementing the same protocol at their composition boundary.
    """

    def resolve(self, reference: ExternalCredentialReference) -> ResolvedExternalCredential:
        if reference.kind.value != "env_var":
            raise CredentialResolutionError(
                f"credential kind '{reference.kind.value}' requires a deployment credential resolver"
            )
        name = reference.reference.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            raise CredentialResolutionError("environment credential reference must be a valid variable name")
        value = os.environ.get(name)
        if not value or not value.strip():
            raise CredentialResolutionError(f"credential environment variable '{name}' is not set")
        return ResolvedExternalCredential(
            reference=reference,
            secret_value=value.strip(),
            issued_subject=reference.subject,
        )
