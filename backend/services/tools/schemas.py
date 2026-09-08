from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator

from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
)
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.types import BusinessObjectRef
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
    lineage: EvidenceLineage | None = None
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


class FinanceRevenueSyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=100, ge=1, le=500)
    context: dict[str, Any] = Field(default_factory=dict)


class FinanceReconciliationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revenue_records: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)


class FinanceInvoiceDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revenue_records: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)


class RuntimeControlVerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(default="Verify local runtime controls", min_length=1, max_length=500)
    controls: tuple[str, ...] = Field(
        default=(
            "network_authority",
            "https_only",
            "private_address_rejection",
            "destination_policy",
            "retry_idempotency",
        ),
        max_length=20,
    )
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    context: dict[str, Any] = Field(default_factory=dict)


class RecordReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    record_id: str = Field(min_length=1, max_length=160)


class RecordWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=1, max_length=80)
    record_id: str | None = Field(default=None, max_length=160)
    data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=160)


class SalesLeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead: dict[str, Any] = Field(default_factory=dict)
    # Mission world-state: bound upstream prospect_candidates / qualified list.
    prospects: list[dict[str, Any]] = Field(default_factory=list)
    account_id: str | None = Field(default=None, max_length=160)
    contact_id: str | None = Field(default=None, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class ResearchReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=1000)
    prospects: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    binding_required: bool = False


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


class SideEffectAuthorizationV2(BaseModel):
    """Task- and payload-bound human approval consumed by runtime authority."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    grant_id: uuid.UUID
    tenant_id: str = Field(min_length=1, max_length=128)
    task_id: uuid.UUID
    allowed_action: str = Field(min_length=1, max_length=160)
    invocation_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: str | None = Field(default=None, min_length=1, max_length=160)
    revocation_reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_lifetime(self) -> SideEffectAuthorizationV2:
        if self.approved_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("side-effect approval timestamps must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("side-effect approval must expire after approval")
        if (self.revoked_by is None) != (self.revoked_at is None):
            raise ValueError("revoked_by and revoked_at must be set together")
        if self.revoked_at is None and self.revocation_reason is not None:
            raise ValueError("revocation_reason requires revoked_at")
        return self


# Browser / unauthenticated client strings must never authorize side effects.
_UNTRUSTED_SIDE_EFFECT_APPROVERS = frozenset(
    {
        "mission-dispatch-ui",
        "mission_dispatch_ui",
        "dispatch-ui-v1",
        "mission-dispatch-ui-compiler",
        "mission_composition_engine",
        "mission_composition_confirm",
        "server:runtime_task_materialization",
    }
)


def is_client_forged_side_effect_approver(approved_by: str) -> bool:
    normalized = approved_by.strip().lower()
    if normalized in _UNTRUSTED_SIDE_EFFECT_APPROVERS:
        return True
    # Any approver that is clearly a UI client label, not an authenticated principal.
    if normalized.startswith("mission-dispatch") or normalized.startswith("mission_dispatch"):
        return True
    return False


def tool_invocation_sha256(invocation: Mapping[str, Any] | ToolInvocation) -> str:
    parsed = invocation if isinstance(invocation, ToolInvocation) else ToolInvocation.model_validate(dict(invocation))
    encoded = json.dumps(
        parsed.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def side_effect_authorized(
    metadata: Mapping[str, Any],
    action: str,
    *,
    tenant_id: str | None = None,
    task_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> bool:
    raw_constraints = metadata.get("execution_constraints")
    if not isinstance(raw_constraints, Mapping):
        raw_constraints = {}
    raw_auth = raw_constraints.get("side_effect_authorization")
    if not isinstance(raw_auth, Mapping):
        return False
    if raw_auth.get("schema_version") == 2:
        try:
            authorization_v2 = SideEffectAuthorizationV2.model_validate(dict(raw_auth))
        except ValidationError:
            return False
        if tenant_id is None or task_id is None:
            return False
        raw_invocation = metadata.get("tool_invocation")
        if not isinstance(raw_invocation, Mapping):
            return False
        current_time = now or datetime.now(UTC)
        try:
            invocation_matches = authorization_v2.invocation_sha256 == tool_invocation_sha256(raw_invocation)
        except ValidationError:
            return False
        return (
            authorization_v2.tenant_id == tenant_id
            and authorization_v2.task_id == task_id
            and authorization_v2.allowed_action == action
            and invocation_matches
            and authorization_v2.revoked_at is None
            and current_time < authorization_v2.expires_at
            and not is_client_forged_side_effect_approver(authorization_v2.approved_by)
        )
    try:
        authorization_v1 = SideEffectAuthorization.model_validate(dict(raw_auth))
    except ValidationError:
        return False
    if is_client_forged_side_effect_approver(authorization_v1.approved_by):
        return False
    return action in authorization_v1.allowed_actions


# PR6+ GTM abilities expansion
class GtmLeadEnrichInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(default="", max_length=160)
    domain: str | None = Field(default=None, max_length=160)
    # Mission world-state: bound qualified/prospect candidates.
    prospects: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_explicit_target(self) -> GtmLeadEnrichInput:
        """Prevent enrichment from silently targeting Ajenda's own profile."""

        if self.company.strip():
            return self
        if any(isinstance(item.get("company"), str) and item["company"].strip() for item in self.prospects):
            return self
        raise ValueError("gtm.lead_enrich requires an explicit company or bound prospect company")


class GtmEmailDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str = Field(default="lead@example.com", max_length=160)
    topic: str = Field(default="follow up", max_length=240)
    tone: str = Field(default="professional", max_length=80)
    # Mission world-state: bound enriched/qualified prospects for draft content.
    prospects: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class DocumentGenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=240)
    tone: str = Field(default="professional", max_length=80)
    recipient: str | None = Field(default=None, max_length=160)
    recipient_name: str | None = Field(default=None, max_length=160)
    context: dict[str, Any] = Field(default_factory=dict)


class DocumentSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=500)
    artifact_type: str | None = Field(default=None, max_length=80)
    review_status: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=10, ge=1, le=50)


class DocumentReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=160)


class RetrievalHybridInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    mission_id: str | None = Field(default=None, max_length=160)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=20)


class GtmEmailSendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=1, max_length=160)
    subject: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=5000)
    artifact_id: str | None = Field(default=None, max_length=160)
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
    # When true, governed public search (DDG) runs — elevates side-effect to EXTERNAL_READ.
    include_public_search: bool = False
    local_fixture_only: bool = False
    limit: int = Field(default=5, ge=1, le=20)
    timeout_seconds: float = Field(default=5.0, ge=0.5, le=10.0)


class WebSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)
    include_internal_records: bool = True
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=15.0)


class ResearchObserveContactsInput(BaseModel):
    """Bound prospect URLs → observed phones/emails from fetched pages. No invented mailboxes."""

    model_config = ConfigDict(extra="forbid")

    prospects: list[dict[str, Any]] = Field(default_factory=list)
    requested_quantity: int = Field(default=5, ge=1, le=20)
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=15.0)
    binding_required: bool = False
    local_fixture_only: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class WebPageReadInput(BaseModel):
    """Public HTTPS page read (single GET + HTML extract). Not a browser session."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=3, max_length=2048)
    timeout_seconds: float = Field(default=8.0, ge=0.5, le=15.0)

    @field_validator("url")
    @classmethod
    def reject_credentialed_page_url(cls, value: str) -> str:
        from backend.services.internet.url_safety import reject_credentialed_url

        return reject_credentialed_url(value, action_name="web.page_read")


class WebBrowserSessionInput(BaseModel):
    """Ephemeral Playwright session — one navigate, then destroy context."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=3, max_length=2048)
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    wait_until: Literal["domcontentloaded", "load", "networkidle"] = "domcontentloaded"
    extract_text: bool = True

    @field_validator("url")
    @classmethod
    def reject_credentialed_browser_url(cls, value: str) -> str:
        from backend.services.internet.url_safety import reject_credentialed_url

        return reject_credentialed_url(value, action_name="web.browser_session")


class WebOpenWriteInput(BaseModel):
    """Flag-gated public-web mutation (POST/PUT/PATCH) with required idempotency."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=2048)
    method: str = Field(default="POST", max_length=10)
    json_body: dict[str, Any] | None = None
    body_text: str | None = Field(default=None, max_length=32_000)
    headers: dict[str, str] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=200)
    timeout_seconds: float = Field(default=10.0, ge=0.5, le=30.0)

    @field_validator("method")
    @classmethod
    def normalize_open_write_method(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized not in {"POST", "PUT", "PATCH"}:
            raise ValueError("web.open_write only allows POST, PUT, or PATCH")
        return normalized

    @field_validator("url")
    @classmethod
    def reject_credentialed_open_write_url(cls, value: str) -> str:
        from backend.services.internet.url_safety import reject_credentialed_url

        return reject_credentialed_url(value, action_name="web.open_write")

    @field_validator("headers")
    @classmethod
    def reject_raw_auth_headers_open_write(cls, value: dict[str, str]) -> dict[str, str]:
        if contains_sensitive_key(value):
            raise ValueError("web.open_write headers must not include raw credential material")
        # Cookie/session are credential carriers even when key names pass fragment checks.
        for key in value:
            normalized = key.strip().lower().replace("_", "-")
            if normalized in {"cookie", "set-cookie", "authorization", "proxy-authorization"}:
                raise ValueError(f"web.open_write headers must not include {key!r}")
            if "session" in normalized or "cookie" in normalized:
                raise ValueError(f"web.open_write headers must not include credential-like header {key!r}")
        return value


# Evidence Intelligence / Decision Support (Slice 1) — explicit evidence-backed recommendation.
# Deterministic algorithm: weighted_criterion_evidence_v1. Does not execute recommendations.


class EvidenceFactStatus(StrEnum):
    KNOWN = "known"
    INFERRED = "inferred"
    MISSING = "missing"


class EvidenceFact(BaseModel):
    """A single evidence fact linked to options and/or criteria for decision scoring.

    Optional about_object_refs (Business Ontology Slice 1) name which business
    objects the claim is about. Callers may omit refs; scoring does not require them.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1, max_length=2000)
    status: EvidenceFactStatus = EvidenceFactStatus.KNOWN
    source: str = Field(default="unspecified", max_length=240)
    confidence: float = Field(default=0.5, ge=0, le=1)
    supports_option_ids: list[str] = Field(default_factory=list)
    supports_criterion_ids: list[str] = Field(default_factory=list)
    about_object_refs: list[BusinessObjectRef] = Field(default_factory=list)
    lineage: EvidenceLineage | None = None
    durable_source_evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Durable EvidenceRecord UUIDs cited by a derived fact. The fact identity remains "
            "distinct from the records that establish its world-evidence ancestry."
        ),
    )

    @field_validator("evidence_id", "claim")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("evidence fields must be non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_lineage_artifact_identity(self) -> EvidenceFact:
        if self.lineage is not None and self.lineage.artifact_evidence_id != self.evidence_id:
            raise ValueError("EvidenceFact lineage artifact_evidence_id must match evidence_id")
        if not self.durable_source_evidence_ids:
            return self
        if self.lineage is None or self.lineage.origin_type != EvidenceOriginType.DERIVED_FACT:
            raise ValueError("durable source evidence requires DERIVED_FACT lineage")
        if self.lineage.resolution != EvidenceLineageResolution.KNOWN:
            raise ValueError("durable source evidence requires known lineage")
        durable_sources = tuple(self.durable_source_evidence_ids)
        if any(str(uuid.UUID(value)) != value for value in durable_sources):
            raise ValueError("durable source evidence IDs must be canonical UUIDs")
        if not all(
            asserted_ids == durable_sources
            for asserted_ids in (
                self.lineage.root_evidence_ids,
                self.lineage.parent_evidence_ids,
                self.lineage.ancestor_evidence_ids,
            )
        ):
            raise ValueError("durable source evidence IDs must exactly match derived lineage ancestry")
        return self

    @field_validator("durable_source_evidence_ids")
    @classmethod
    def canonicalize_durable_sources(cls, values: list[str]) -> list[str]:
        return sorted({value.strip() for value in values if value.strip()})


class DecisionCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=240)
    weight: float = Field(default=1.0, gt=0, le=100)
    required: bool = False

    @field_validator("criterion_id", "label")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("criterion fields must be non-empty")
        return normalized


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=1000)
    intervention_key: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("option_id", "label", "intervention_key")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("option fields must be non-empty")
        return normalized


class DecisionRecommendInput(BaseModel):
    """Input for decision.recommend_next_action.

    Slice 1: goal (string), options, criteria, evidence, constraints.
    Slice 2 (optional): structured Goal / subject refs / KPI / state / events.
    Optional commercial fields do not change scoring; they frame the decision
    for evaluation intelligence later. Old callers remain valid.
    """

    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=1000)
    options: list[DecisionOption] = Field(default_factory=list)
    criteria: list[DecisionCriterion] = Field(default_factory=list)
    evidence: list[EvidenceFact] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    # Commercial State Slice 2 — all optional, non-breaking
    subject_refs: list[BusinessObjectRef] = Field(
        default_factory=list,
        description="Business objects this recommendation concerns",
    )
    goal_ref: Goal | None = Field(
        default=None,
        description="Structured Goal; complements the free-text goal field",
    )
    kpis: list[Kpi] = Field(
        default_factory=list,
        description="KPI measurements/targets relevant to the goal",
    )
    state_snapshot: BusinessStateSnapshot | None = Field(
        default=None,
        description="Current believed state of the primary subject",
    )
    recent_events: list[BusinessEvent] = Field(
        default_factory=list,
        description="Recent change events; not scored in v1 algorithm",
    )

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("goal must be non-empty")
        return normalized
