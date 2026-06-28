from __future__ import annotations

import uuid
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from backend.services.security.redaction import contains_sensitive_key

TOOL_INVOCATION_SCHEMA_VERSION = 1
ACTION_RESULT_SCHEMA_VERSION = 1


class SideEffectClass(StrEnum):
    NONE = "none"
    INTERNAL_READ = "internal_read"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_READ = "external_read"
    EXTERNAL_WRITE = "external_write"
    EXTERNAL_SEND = "external_send"
    EXTERNAL_PUBLISH = "external_publish"

    @property
    def has_side_effect(self) -> bool:
        return self in {
            SideEffectClass.INTERNAL_WRITE,
            SideEffectClass.EXTERNAL_WRITE,
            SideEffectClass.EXTERNAL_SEND,
            SideEffectClass.EXTERNAL_PUBLISH,
        }


class CredentialReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    credential_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=120)
    credential_type: str = Field(min_length=1, max_length=80)

    @field_validator("credential_id", "provider", "credential_type")
    @classmethod
    def normalize_required_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("credential reference fields must be non-empty")
        return normalized


class RuntimeCredentialMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: CredentialReference
    secret_value: str = Field(min_length=1, repr=False, exclude=True)
    injected_headers: dict[str, str] = Field(default_factory=dict, repr=False, exclude=True)
    trusted_destination_hosts: tuple[str, ...] = Field(default_factory=tuple, repr=False, exclude=True)


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    action: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=200)
    credential_reference: CredentialReference | None = None

    @field_validator("action")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("action must be non-empty")
        return normalized


class ActionRuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    tenant_id: str = Field(min_length=1)
    task_id: uuid.UUID
    mission_id: uuid.UUID | None = None
    worker_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    session_factory: Any | None = None
    vector_session_factory: Any | None = None
    runtime_credentials: dict[str, RuntimeCredentialMaterial] = Field(default_factory=dict, repr=False)
    runtime_cache: dict[str, Any] = Field(default_factory=dict, repr=False)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str = Field(min_length=1, max_length=120)
    evidence_source: str = Field(min_length=1, max_length=240)
    action_name: str = Field(min_length=1, max_length=160)
    tool_provider: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    mission_id: str | None = None
    summary: str = Field(min_length=1, max_length=1000)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    records_inspected: list[str] = Field(default_factory=list)
    records_changed: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    collection_status: str = Field(default="collected", min_length=1, max_length=80)


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    action: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=160)
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    records_inspected: list[str] = Field(default_factory=list)
    records_changed: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class RecordSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    query: str = Field(default="", max_length=240)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=50)


class RecordReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    record_id: str = Field(min_length=1, max_length=160)


class RecordWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    record_id: str | None = Field(default=None, max_length=160)
    data: dict[str, Any] = Field(default_factory=dict)


class SalesLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: dict[str, Any] = Field(default_factory=dict)
    account_id: str | None = Field(default=None, max_length=160)
    contact_id: str | None = Field(default=None, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class FollowupDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(default="there", max_length=160)
    topic: str = Field(default="next steps", max_length=240)
    tone: str = Field(default="professional", max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)


class HttpRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="GET", max_length=10)
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=5.0, ge=0.1, le=10.0)
    allowed_hosts: list[str] = Field(default_factory=list)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("unsupported HTTP method")
        return normalized

    @field_validator("headers")
    @classmethod
    def reject_raw_auth_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if contains_sensitive_key(value):
            raise ValueError("http.request headers must not include raw credential material")
        return value


class WebhookDispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: uuid.UUID | None = None
    attempt_number: int = Field(default=1, ge=1, le=100)


class CalendarReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=160)
    start: str | None = Field(default=None, max_length=80)
    end: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=10, ge=1, le=50)


class CalendarCreateEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="primary", min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    start: str = Field(min_length=1, max_length=80)
    end: str = Field(min_length=1, max_length=80)
    attendees: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=1000)


class SideEffectAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    allowed_actions: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=500)
    approved_by: str = Field(min_length=1, max_length=160)


def side_effect_authorized(metadata: Mapping[str, Any], action: str) -> bool:
    raw_constraints = metadata.get("execution_constraints")
    if not isinstance(raw_constraints, Mapping):
        raw_constraints = {}
    raw_auth = raw_constraints.get("side_effect_authorization")
    if not isinstance(raw_auth, Mapping):
        return False
    authorization = SideEffectAuthorization.model_validate(dict(raw_auth))
    return action in authorization.allowed_actions


# PR6+ GTM abilities expansion
class GtmLeadEnrichInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(min_length=1, max_length=160)
    domain: str | None = Field(default=None, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class GtmEmailDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(default="lead@example.com", max_length=160)
    topic: str = Field(default="follow up", max_length=240)
    tone: str = Field(default="professional", max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)


class RetrievalHybridInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mission_id: str | None = Field(default=None, max_length=160)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class GtmEmailSendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=5000)
    context: dict[str, Any] = Field(default_factory=dict)


class GtmEmailCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="is:unread", min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)


class GtmCrmUpsertInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(default="lead", max_length=80)
    data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class GtmSocialPublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str = Field(default="twitter", max_length=80)
    content: str = Field(min_length=1, max_length=280)
    context: dict[str, Any] = Field(default_factory=dict)


class WebResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    company: str | None = Field(default=None, max_length=160)
    domain: str | None = Field(default=None, max_length=160)
    fetch_public_page: bool = False
    limit: int = Field(default=5, ge=1, le=20)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)
    include_internal_records: bool = True
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=15.0)
