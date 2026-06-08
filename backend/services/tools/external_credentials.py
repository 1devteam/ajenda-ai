"""External provider credential contracts.

These contracts describe credential references for future external tool providers.
They do not store plaintext secrets, decrypt credentials, call external services,
or grant runtime execution authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExternalProviderName(StrEnum):
    """Supported external provider identifiers."""

    GOOGLE_CALENDAR = "google_calendar"
    GMAIL = "gmail"
    GITHUB = "github"
    CRM = "crm"
    BROWSER = "browser"
    MCP = "mcp"


class CredentialReferenceKind(StrEnum):
    """Where a credential is expected to be resolved from at runtime."""

    ENV_VAR = "env_var"
    SECRET_MANAGER = "secret_manager"
    K8S_SECRET = "k8s_secret"
    OAUTH_TOKEN_STORE = "oauth_token_store"


class ExternalCredentialReference(BaseModel):
    """Non-secret reference to an external provider credential."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider: ExternalProviderName
    tenant_id: str = Field(min_length=1, max_length=160)
    kind: CredentialReferenceKind
    reference: str = Field(min_length=1, max_length=500)
    scopes: tuple[str, ...] = ()
    subject: str | None = Field(default=None, max_length=240)
    rotation_required: bool = True
    plaintext_secret: None = None

    @field_validator("tenant_id", "reference")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("scopes")
    @classmethod
    def normalize_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("scope entries must be non-empty")
            normalized.append(stripped)
        return tuple(normalized)

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None
