from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SideEffectClass = Literal[
    "none", "internal_write", "external_read", "external_write", "external_send", "external_publish"
]


class ToolInvocationEnvelope(BaseModel):
    """Versioned runtime metadata envelope consumed by the ``tool.invoke`` handler."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    action: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = Field(default=None, min_length=1, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def _validate_schema_version(self) -> ToolInvocationEnvelope:
        if self.schema_version != 1:
            raise ValueError("tool invocation schema_version must be 1")
        self.action = self.action.strip()
        if not self.action:
            raise ValueError("tool invocation action must be non-empty")
        if self.provider is not None:
            self.provider = self.provider.strip()
            if not self.provider:
                raise ValueError("tool invocation provider must be non-empty")
        return self


class EvidenceItem(BaseModel):
    """Evidence-shaped item carried in task-output lineage."""

    model_config = ConfigDict(extra="forbid")

    evidence_type: str = Field(min_length=1, max_length=64)
    evidence_source: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2000)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    artifact_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)
    trust_signal: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    collection_status: str = Field(default="collected", min_length=1, max_length=32)

    @field_validator("evidence_type", "evidence_source", "summary", "collection_status")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("evidence text fields must be non-empty")
        return value


class ActionResult(BaseModel):
    """Canonical action output returned by executable action functions."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    status: Literal["completed"] = "completed"
    side_effect_class: SideEffectClass = "none"
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)


@dataclass(slots=True)
class ActionExecutionContext:
    """Tenant/runtime-scoped context passed to tool actions."""

    tenant_id: str
    task_id: uuid.UUID
    mission_id: uuid.UUID
    worker_id: str
    lease_id: str
    session_factory: Any
    provider: str | None = None
    http_client: httpx.Client | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class LocalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=160)
    record_type: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    fields: dict[str, Any] = Field(default_factory=dict)


class RecordSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=64)
    query: str = Field(default="", max_length=255)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=10, ge=1, le=100)
    simulate_provider_failure: bool = False


class RecordReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=64)
    record_id: str = Field(min_length=1, max_length=160)
    simulate_provider_failure: bool = False


class RecordWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=64)
    record_id: str | None = Field(default=None, min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=255)
    fields: dict[str, Any] = Field(default_factory=dict)
    simulate_provider_failure: bool = False


class SalesRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(default="lead", min_length=1, max_length=64)
    record_id: str = Field(min_length=1, max_length=160)


class SalesDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_name: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    topic: str = Field(min_length=1, max_length=255)
    tone: str = Field(default="professional", min_length=1, max_length=64)


class SalesActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=160)
    activity_type: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FollowupTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=255)
    due_at: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HttpRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(default="GET", min_length=1, max_length=10)
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=30)

    @model_validator(mode="after")
    def _validate_request(self) -> HttpRequestInput:
        self.method = self.method.upper().strip()
        if self.method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("http method is not supported")
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("http action requires an absolute http or https URL")
        host = parsed.hostname
        if host:
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                ip = None
            if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast):
                raise ValueError("http action cannot target private or loopback IP addresses")
        return self


class WebhookDispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: uuid.UUID | None = None
    attempt_number: int = Field(default=1, ge=1, le=100)


class CalendarReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="default", min_length=1, max_length=160)
    limit: int = Field(default=25, ge=1, le=100)


class CalendarCreateEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_id: str = Field(default="default", min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=255)
    start_at: str = Field(min_length=1, max_length=64)
    end_at: str = Field(min_length=1, max_length=64)
    attendees: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)
