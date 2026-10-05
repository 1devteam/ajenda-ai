from __future__ import annotations

import json
import re
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_business_profile_repository
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.business_profile import (
    BUSINESS_PROFILE_SCHEMA_VERSION,
    BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
    BusinessProfile,
    BusinessProfileSuggestion,
)
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.business_profile_categories import (
    BUSINESS_PROFILE_CATEGORY_FIELDS,
    missing_profile_categories,
)
from backend.services.business_profile_record_sync import sync_profile_to_internal_records
from backend.services.vertical_ops.plan_templates import get_vertical_mission_template

router = APIRouter(prefix="/business-profile", tags=["business-profile"])

SuggestionStatus = Literal[
    "pending",
    "approved",
    "edited",
    "declined",
    "dismissed",
    "superseded",
    "review_rolled_back",
    "application_reverted",
]

MAX_PROFILE_JSON_BYTES = 16_384
MAX_PROFILE_JSON_DEPTH = 8
MAX_PROFILE_JSON_KEYS = 128
_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_:-]{0,95}$")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _actor_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    subject_id = getattr(principal, "subject_id", None)
    return str(subject_id or "unknown")


def _normalize_category(value: str) -> str:
    normalized = "_".join(value.strip().lower().split())
    if not normalized:
        raise ValueError("category must be non-empty")
    if not _CATEGORY_PATTERN.fullmatch(normalized):
        raise ValueError("category must use lowercase letters, numbers, underscores, hyphens, or colons")
    return normalized


def _validate_json_payload(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    def _walk(node: Any, *, depth: int, key_count: list[int]) -> None:
        if depth > MAX_PROFILE_JSON_DEPTH:
            raise ValueError(f"{field_name} exceeds maximum JSON depth")
        if isinstance(node, dict):
            key_count[0] += len(node)
            if key_count[0] > MAX_PROFILE_JSON_KEYS:
                raise ValueError(f"{field_name} exceeds maximum JSON key count")
            for key, child in node.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} JSON object keys must be strings")
                _walk(child, depth=depth + 1, key_count=key_count)
            return
        if isinstance(node, list):
            for child in node:
                _walk(child, depth=depth + 1, key_count=key_count)
            return
        if node is not None and not isinstance(node, str | int | float | bool):
            raise ValueError(f"{field_name} contains a non-JSON value")

    _walk(value, depth=1, key_count=[0])
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PROFILE_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum JSON size")
    return value


def _append_business_profile_audit_event(
    *,
    db: Session,
    tenant_id: str,
    action: str,
    actor_id: str,
    details: str,
    payload: dict[str, Any],
    mission_id: UUID | None = None,
) -> None:
    AuditEventRepository(db).append(
        AuditEvent(
            tenant_id=tenant_id,
            mission_id=mission_id,
            category="business_profile",
            action=action,
            actor=actor_id,
            details=details,
            payload_json=payload,
        )
    )


def _parse_mission_id(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("source_context.mission_id must be a valid UUID") from exc


def _validate_suggestion_mission_id(*, db: Session, tenant_id: str, mission_id: UUID | None) -> UUID | None:
    if mission_id is None:
        return None
    if MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id) is None:
        raise ValueError("business profile suggestion mission_id not found for tenant")
    return mission_id


class BusinessProfileRead(BaseModel):
    """Stable read shape for Mission Brief consumers of approved profile facts."""

    profile_id: UUID | None
    tenant_id: str
    status: str
    approved_facts: dict[str, Any]
    provenance: dict[str, Any]
    schema_version: int
    created_at: str | None
    updated_at: str | None


class BusinessProfileCategoryRead(BaseModel):
    category: str
    status: Literal["complete", "missing"]
    fields: list[str]


class BusinessProfileReadinessRead(BaseModel):
    """Read-only category coverage used before selecting a vertical template."""

    tenant_id: str
    profile_id: UUID | None
    template_id: str | None
    required_profile_categories: list[str]
    missing_required_categories: list[str]
    ready_for_template: bool
    ready: bool
    missing_categories: list[str]
    categories: list[BusinessProfileCategoryRead]


class BusinessProfileFactUpsert(BaseModel):
    """Explicit approved-fact write request; no profile truth is inferred silently."""

    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, Any] = Field(min_length=1)
    provenance_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("approved_fact", "provenance_metadata")
    @classmethod
    def _validate_payloads(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_json_payload(value, field_name=info.field_name)


class BusinessProfileSuggestionCreate(BaseModel):
    """Create a tenant-owned suggestion without mutating approved Business Profile truth."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID | None = None
    suggested_category: str = Field(min_length=1, max_length=96)
    suggested_fact: dict[str, Any] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=500)
    source_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("suggested_category")
    @classmethod
    def _normalize_suggested_category(cls, value: str) -> str:
        return _normalize_category(value)

    @field_validator("rationale")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty")
        return value

    @field_validator("suggested_fact", "source_context")
    @classmethod
    def _validate_payloads(cls, value: dict[str, Any], info: Any) -> dict[str, Any]:
        return _validate_json_payload(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _normalize_source_context_mission_id(self) -> BusinessProfileSuggestionCreate:
        raw_source_context_mission_id = self.source_context.get("mission_id")
        if raw_source_context_mission_id is None:
            return self
        source_context_mission_id = _parse_mission_id(raw_source_context_mission_id)
        if self.mission_id is not None and self.mission_id != source_context_mission_id:
            raise ValueError("mission_id must match source_context.mission_id when both are provided")
        self.mission_id = source_context_mission_id
        self.source_context = {**self.source_context, "mission_id": str(source_context_mission_id)}
        return self


class BusinessProfileSuggestionResolveWithEdit(BaseModel):
    """Approve a pending suggestion with a user-approved edited fact."""

    model_config = ConfigDict(extra="forbid")

    approved_fact: dict[str, Any] = Field(min_length=1)

    @field_validator("approved_fact")
    @classmethod
    def _validate_approved_fact(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_payload(value, field_name="approved_fact")


class BusinessProfileSuggestionRead(BaseModel):
    """Business Profile suggestion lifecycle response contract."""

    suggestion_id: UUID
    tenant_id: str
    profile_id: UUID | None
    mission_id: UUID | None
    suggested_category: str
    suggested_fact: dict[str, Any]
    rationale: str
    source_context: dict[str, Any]
    status: str
    resolution: dict[str, Any]
    schema_version: int
    created_at: str
    resolved_at: str | None


class BusinessProfileSuggestionListRead(BaseModel):
    """List response for tenant-owned Business Profile suggestions."""

    suggestions: list[BusinessProfileSuggestionRead]


class BusinessProfileSuggestionResolutionRead(BaseModel):
    """Suggestion resolution response, including profile truth when promoted."""

    profile: BusinessProfileRead | None = None
    suggestion: BusinessProfileSuggestionRead


class BusinessProfileHistoryEventRead(BaseModel):
    """Bounded profile history/audit event read shape."""

    event_type: str
    category: str | None = None
    decision: str | None = None
    actor_id: str | None = None
    occurred_at: str | None = None
    profile_id: UUID | None = None
    suggestion_id: UUID | None = None
    mission_id: UUID | None = None
    current_fact: dict[str, Any] | None = None
    approved_fact: dict[str, Any] | None = None
    superseded_fact: dict[str, Any] | None = None
    source_context: dict[str, Any] | None = None


class BusinessProfileHistoryRead(BaseModel):
    """Read-only Business Profile history/audit response."""

    profile: BusinessProfileRead
    events: list[BusinessProfileHistoryEventRead]


def _profile_to_read(profile: BusinessProfile | None, *, tenant_id: str) -> BusinessProfileRead:
    if profile is None:
        return BusinessProfileRead(
            profile_id=None,
            tenant_id=tenant_id,
            status="missing",
            approved_facts={},
            provenance={},
            schema_version=BUSINESS_PROFILE_SCHEMA_VERSION,
            created_at=None,
            updated_at=None,
        )
    return BusinessProfileRead(
        profile_id=profile.id,
        tenant_id=profile.tenant_id,
        status=profile.status,
        approved_facts=profile.approved_facts,
        provenance=profile.provenance,
        schema_version=profile.schema_version,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


def _suggestion_to_read(suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestionRead:
    return BusinessProfileSuggestionRead(
        suggestion_id=suggestion.id,
        tenant_id=suggestion.tenant_id,
        profile_id=suggestion.profile_id,
        mission_id=suggestion.mission_id,
        suggested_category=suggestion.suggested_category,
        suggested_fact=suggestion.suggested_fact,
        rationale=suggestion.rationale,
        source_context=suggestion.source_context,
        status=suggestion.status,
        resolution=suggestion.resolution,
        schema_version=suggestion.schema_version,
        created_at=suggestion.created_at.isoformat(),
        resolved_at=suggestion.resolved_at.isoformat() if suggestion.resolved_at else None,
    )


def _get_or_create_active_profile(repo: BusinessProfileRepository, *, tenant_id: str) -> BusinessProfile:
    return repo.get_or_create_active_profile(tenant_id=tenant_id)


def _history_to_read(
    *, tenant_id: str, profile: BusinessProfile | None, suggestions: list[BusinessProfileSuggestion]
) -> BusinessProfileHistoryRead:
    events: list[BusinessProfileHistoryEventRead] = []
    if profile is not None:
        for category, provenance in sorted((profile.provenance or {}).items()):
            if not isinstance(provenance, dict):
                continue
            events.append(
                BusinessProfileHistoryEventRead(
                    event_type="approved_fact",
                    category=str(category),
                    decision=str(provenance.get("decision")) if provenance.get("decision") is not None else None,
                    actor_id=str(provenance.get("actor_id")) if provenance.get("actor_id") is not None else None,
                    occurred_at=str(provenance.get("updated_at") or provenance.get("resolved_at"))
                    if (provenance.get("updated_at") or provenance.get("resolved_at")) is not None
                    else None,
                    profile_id=profile.id,
                    suggestion_id=UUID(str(provenance["suggestion_id"])) if provenance.get("suggestion_id") else None,
                    current_fact=(profile.approved_facts or {}).get(category),
                    superseded_fact=provenance.get("superseded_fact"),
                )
            )
    for suggestion in suggestions:
        resolution = suggestion.resolution or {}
        events.append(
            BusinessProfileHistoryEventRead(
                event_type="suggestion",
                category=suggestion.suggested_category,
                decision=suggestion.status,
                actor_id=str(resolution.get("actor_id")) if resolution.get("actor_id") is not None else None,
                occurred_at=(suggestion.resolved_at or suggestion.created_at).isoformat(),
                profile_id=suggestion.profile_id,
                suggestion_id=suggestion.id,
                mission_id=suggestion.mission_id,
                approved_fact=resolution.get("approved_fact"),
                superseded_fact=resolution.get("superseded_fact"),
                source_context=suggestion.source_context,
            )
        )
    events.sort(key=lambda event: event.occurred_at or "")
    return BusinessProfileHistoryRead(profile=_profile_to_read(profile, tenant_id=tenant_id), events=events)


def _get_pending_suggestion_or_404(
    repo: BusinessProfileRepository, *, suggestion_id: UUID, tenant_id: str
) -> BusinessProfileSuggestion:
    suggestion = repo.get_suggestion_for_tenant(suggestion_id=suggestion_id, tenant_id=tenant_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="business profile suggestion not found for tenant")
    return suggestion


def _resolve_value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


def _sync_profile_internal_records(*, db: Session, tenant_id: str, profile: BusinessProfile) -> None:
    sync_profile_to_internal_records(
        session=db,
        tenant_id=tenant_id,
        approved_facts=profile.approved_facts if isinstance(profile.approved_facts, dict) else {},
    )


@router.get("", response_model=BusinessProfileRead)
def read_business_profile(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileRead:
    """Read active tenant Business Profile facts without mutating profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_scope)
    return _profile_to_read(profile, tenant_id=tenant_scope)


@router.get("/readiness", response_model=BusinessProfileReadinessRead)
def read_business_profile_readiness(
    request: Request,
    template_id: str | None = Query(default=None, min_length=1, max_length=160),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    profile_repo: BusinessProfileRepository = Depends(get_business_profile_repository),
) -> BusinessProfileReadinessRead:
    """Report canonical profile category coverage without creating or mutating profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    profile = profile_repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    approved_facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
    required_categories = tuple(BUSINESS_PROFILE_CATEGORY_FIELDS)
    if template_id is not None:
        try:
            required_categories = get_vertical_mission_template(template_id).required_profile_categories
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    missing = missing_profile_categories(approved_facts, tuple(BUSINESS_PROFILE_CATEGORY_FIELDS))
    missing_required = missing_profile_categories(approved_facts, required_categories)
    categories = [
        BusinessProfileCategoryRead(
            category=category,
            status="missing" if category in missing else "complete",
            fields=list(fields),
        )
        for category, fields in BUSINESS_PROFILE_CATEGORY_FIELDS.items()
    ]
    return BusinessProfileReadinessRead(
        tenant_id=tenant_scope,
        profile_id=profile.id if profile is not None else None,
        template_id=template_id,
        required_profile_categories=list(required_categories),
        missing_required_categories=missing_required,
        ready_for_template=not missing_required,
        ready=not missing,
        missing_categories=missing,
        categories=categories,
    )


@router.get("/history", response_model=BusinessProfileHistoryRead)
def read_business_profile_history(
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileHistoryRead:
    """Read tenant-owned Business Profile history and suggestion audit decisions without mutation."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    history = BusinessProfileRepository(db).list_profile_history_for_tenant(tenant_id=tenant_scope)
    return _history_to_read(
        tenant_id=tenant_scope,
        profile=history["profile"],  # type: ignore[arg-type]
        suggestions=history["suggestions"],  # type: ignore[arg-type]
    )


@router.put("/facts/{category}", response_model=BusinessProfileRead)
def upsert_business_profile_fact(
    category: str,
    body: BusinessProfileFactUpsert,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileRead:
    """Explicitly create or update one approved Business Profile fact."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated = repo.upsert_approved_fact(
            profile=profile,
            category=_normalize_category(category),
            approved_fact=body.approved_fact,
            actor_id=_actor_id(request),
            updated_at=_utcnow(),
            provenance_metadata=body.provenance_metadata,
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    normalized_category = _normalize_category(category)
    _sync_profile_internal_records(db=db, tenant_id=tenant_scope, profile=updated)
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_fact_upserted",
        actor_id=_actor_id(request),
        details="Business Profile approved fact was explicitly upserted.",
        payload={"profile_id": str(updated.id), "category": normalized_category},
    )
    return _profile_to_read(updated, tenant_id=tenant_scope)


@router.post("/suggestions", response_model=BusinessProfileSuggestionRead, status_code=status.HTTP_201_CREATED)
def create_business_profile_suggestion(
    body: BusinessProfileSuggestionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionRead:
    """Create a pending profile update suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    try:
        mission_id = _validate_suggestion_mission_id(db=db, tenant_id=tenant_scope, mission_id=body.mission_id)
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    suggestion = repo.add_suggestion(
        BusinessProfileSuggestion(
            tenant_id=tenant_scope,
            profile_id=profile.id if profile else None,
            mission_id=mission_id,
            suggested_category=body.suggested_category,
            suggested_fact=body.suggested_fact,
            rationale=body.rationale,
            source_context=body.source_context,
            schema_version=BUSINESS_PROFILE_SUGGESTION_SCHEMA_VERSION,
        )
    )
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_created",
        actor_id=_actor_id(request),
        details="Business Profile suggestion was created without promoting profile truth.",
        payload={"suggestion_id": str(suggestion.id), "category": suggestion.suggested_category},
        mission_id=mission_id,
    )
    return _suggestion_to_read(suggestion)


@router.get("/suggestions", response_model=BusinessProfileSuggestionListRead)
def list_business_profile_suggestions(
    request: Request,
    status_filter: SuggestionStatus | None = Query(default=None, alias="status"),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionListRead:
    """List tenant-owned profile update suggestions, optionally by lifecycle status."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_READ, tenant_id=tenant_id)
    records = BusinessProfileRepository(db).list_suggestions_for_tenant(tenant_id=str(tenant_id), status=status_filter)
    return BusinessProfileSuggestionListRead(suggestions=[_suggestion_to_read(record) for record in records])


@router.post("/suggestions/{suggestion_id}/approve", response_model=BusinessProfileSuggestionResolutionRead)
def approve_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Approve a pending suggestion as-is and promote that fact to profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        repo.require_pending_suggestion(suggestion)
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated_profile, updated_suggestion = repo.approve_suggestion_as_is(
            profile=profile,
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _sync_profile_internal_records(db=db, tenant_id=tenant_scope, profile=updated_profile)
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_approved",
        actor_id=_actor_id(request),
        details="Business Profile suggestion was approved and promoted to profile truth.",
        payload={"profile_id": str(updated_profile.id), "suggestion_id": str(updated_suggestion.id)},
        mission_id=updated_suggestion.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(
        profile=_profile_to_read(updated_profile, tenant_id=tenant_scope),
        suggestion=_suggestion_to_read(updated_suggestion),
    )


@router.post("/suggestions/{suggestion_id}/approve-with-edits", response_model=BusinessProfileSuggestionResolutionRead)
def approve_business_profile_suggestion_with_edits(
    suggestion_id: UUID,
    body: BusinessProfileSuggestionResolveWithEdit,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Approve a pending suggestion with edits and store only the edited approved fact."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        repo.require_pending_suggestion(suggestion)
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    profile = _get_or_create_active_profile(repo, tenant_id=tenant_scope)
    try:
        updated_profile, updated_suggestion = repo.approve_suggestion_with_edit(
            profile=profile,
            suggestion=suggestion,
            approved_fact=body.approved_fact,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _sync_profile_internal_records(db=db, tenant_id=tenant_scope, profile=updated_profile)
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_edited",
        actor_id=_actor_id(request),
        details="Business Profile suggestion was edited and promoted to profile truth.",
        payload={"profile_id": str(updated_profile.id), "suggestion_id": str(updated_suggestion.id)},
        mission_id=updated_suggestion.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(
        profile=_profile_to_read(updated_profile, tenant_id=tenant_scope),
        suggestion=_suggestion_to_read(updated_suggestion),
    )


@router.post("/suggestions/{suggestion_id}/decline", response_model=BusinessProfileSuggestionResolutionRead)
def decline_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Decline a pending suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.decline_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_declined",
        actor_id=_actor_id(request),
        details="Business Profile suggestion was declined without promoting profile truth.",
        payload={"suggestion_id": str(updated_suggestion.id)},
        mission_id=updated_suggestion.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated_suggestion))


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=BusinessProfileSuggestionResolutionRead)
def dismiss_business_profile_suggestion(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Dismiss a pending suggestion without promoting durable profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated_suggestion = repo.dismiss_suggestion(
            suggestion=suggestion,
            resolved_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_dismissed",
        actor_id=_actor_id(request),
        details="Business Profile suggestion was dismissed without promoting profile truth.",
        payload={"suggestion_id": str(updated_suggestion.id)},
        mission_id=updated_suggestion.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated_suggestion))


@router.post("/suggestions/{suggestion_id}/review-rollback", response_model=BusinessProfileSuggestionResolutionRead)
def rollback_business_profile_suggestion_review(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Record review rollback without changing already-applied profile truth."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    try:
        updated = repo.rollback_suggestion_review(
            suggestion=suggestion,
            rolled_back_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_review_rolled_back",
        actor_id=_actor_id(request),
        details="Business Profile suggestion review was rolled back; profile truth was not changed.",
        payload={"suggestion_id": str(updated.id), "rollback_type": "review_rolled_back"},
        mission_id=updated.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(profile=None, suggestion=_suggestion_to_read(updated))


@router.post("/suggestions/{suggestion_id}/application-revert", response_model=BusinessProfileSuggestionResolutionRead)
def revert_business_profile_suggestion_application(
    suggestion_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessProfileSuggestionResolutionRead:
    """Apply a compensating profile mutation for one unchanged application."""
    require_route_permission(request=request, db=db, permission=Permission.BUSINESS_PROFILE_MANAGE, tenant_id=tenant_id)
    tenant_scope = str(tenant_id)
    repo = BusinessProfileRepository(db)
    suggestion = _get_pending_suggestion_or_404(repo, suggestion_id=suggestion_id, tenant_id=tenant_scope)
    profile = repo.get_active_profile_for_tenant(tenant_id=tenant_scope)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="active business profile not found")
    try:
        updated_profile, updated = repo.revert_suggestion_application(
            profile=profile,
            suggestion=suggestion,
            reverted_at=_utcnow(),
            actor_id=_actor_id(request),
        )
    except ValueError as exc:
        raise _resolve_value_error(exc) from exc
    _sync_profile_internal_records(db=db, tenant_id=tenant_scope, profile=updated_profile)
    _append_business_profile_audit_event(
        db=db,
        tenant_id=tenant_scope,
        action="business_profile_suggestion_application_reverted",
        actor_id=_actor_id(request),
        details="Business Profile application was reverted with a verified compensating mutation.",
        payload={
            "profile_id": str(updated_profile.id),
            "suggestion_id": str(updated.id),
            "rollback_type": "application_reverted",
        },
        mission_id=updated.mission_id,
    )
    return BusinessProfileSuggestionResolutionRead(
        profile=_profile_to_read(updated_profile, tenant_id=tenant_scope),
        suggestion=_suggestion_to_read(updated),
    )
