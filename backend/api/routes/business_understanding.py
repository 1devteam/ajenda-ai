"""Tenant-scoped business observations and declarative need hypotheses.

This API records attributed observations and revisions only.  It cannot create
missions, tasks, queue entries, provider calls, or authorization decisions.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.business_understanding import BusinessNeedRevision, BusinessObservation
from backend.repositories.business_understanding_repository import (
    BusinessNeedRevisionConflict,
    BusinessUnderstandingRepository,
)
from backend.services.business_understanding.reasoning import (
    BusinessNeedAssessmentResult,
    BusinessNeedReasoningService,
    NeedAssessmentRequest,
)
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
    SourceReference,
)
from backend.services.ontology.commercial_state import Goal, Kpi

router = APIRouter(prefix="/business-understanding", tags=["business-understanding"])

ObservationSourceKind = Literal[
    "business_profile",
    "tenant_internal_record",
    "evidence",
    "outcome_review",
    "knowledge_artifact",
    "external_provider",
    "customer_instruction",
]
NeedOrigin = Literal["explicitly_stated", "observed", "inferred"]
NeedStatus = Literal[
    "recognized",
    "monitoring",
    "challenged",
    "response_proposed",
    "impact_monitored",
    "resolved",
    "disproven",
    "superseded",
]


def _actor_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    return str(getattr(principal, "subject_id", None) or "unknown")


class ObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: ObservationSourceKind
    source_reference: dict[str, Any] = Field(min_length=1)
    subject_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    observation_summary: str = Field(min_length=1, max_length=5000)
    observed_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)
    limitations: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    contradicts_observation_id: UUID | None = None
    corrects_observation_id: UUID | None = None

    @field_validator("observation_summary")
    @classmethod
    def _non_empty_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("observation_summary must be non-empty")
        return value


class MeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Goal
    kpis: list[Kpi] = Field(min_length=1, max_length=100)
    subject_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    source_kind: Literal["customer_attested", "source_verified"] = "customer_attested"
    source_reference: dict[str, Any] = Field(min_length=1)
    source_version: str = Field(min_length=1, max_length=160)
    measurement_period_start: datetime | None = None
    measurement_period_end: datetime | None = None
    observed_at: datetime
    limitations: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _validate_measurement_contract(self) -> MeasurementCreate:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.measurement_period_start and (
            self.measurement_period_start.tzinfo is None or self.measurement_period_start.utcoffset() is None
        ):
            raise ValueError("measurement_period_start must be timezone-aware")
        if self.measurement_period_end and (
            self.measurement_period_end.tzinfo is None or self.measurement_period_end.utcoffset() is None
        ):
            raise ValueError("measurement_period_end must be timezone-aware")
        if (
            self.measurement_period_start is not None
            and self.measurement_period_end is not None
            and self.measurement_period_end < self.measurement_period_start
        ):
            raise ValueError("measurement period is invalid")
        expected = {item.model_dump(mode="json") for item in self.goal.subject_refs}
        supplied = {str(item) for item in self.subject_references}
        if expected and {str(item) for item in expected} != supplied:
            raise ValueError("measurement subjects must match goal subjects")
        return self


class NeedRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    origin: NeedOrigin
    status: NeedStatus = "recognized"
    subject_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    objective_reference: dict[str, Any] | None = None
    condition_summary: str = Field(min_length=1, max_length=5000)
    uncertainty: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    priority: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    observation_ids: list[UUID] = Field(default_factory=list, max_length=100)
    related_need_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    candidate_responses: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    proposal_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    mission_references: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    impact_assessment: dict[str, Any] | None = None
    resolution_observation_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("condition_summary")
    @classmethod
    def _non_empty_condition(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("condition_summary must be non-empty")
        return value

    @model_validator(mode="after")
    def _server_owns_initial_need_identity(self) -> NeedRevisionCreate:
        if self.expected_revision == 0 and self.need_id is not None:
            raise ValueError("initial need identity is server-assigned")
        if self.expected_revision > 0 and self.need_id is None:
            raise ValueError("need_id is required when revising a need")
        return self


class RecognitionCreate(BaseModel):
    """Persist an observation and its initial hypothesis atomically."""

    model_config = ConfigDict(extra="forbid")

    observation: ObservationCreate
    need: NeedRevisionCreate

    @field_validator("need")
    @classmethod
    def _only_initial_revision(cls, value: NeedRevisionCreate) -> NeedRevisionCreate:
        if value.need_id is not None or value.expected_revision != 0:
            raise ValueError("recognition must create the initial need revision")
        return value


class ObservationRead(BaseModel):
    observation_id: UUID
    tenant_id: str
    source_kind: str
    source_reference: dict[str, Any]
    source_fingerprint: str
    producer: str
    subject_references: list[dict[str, Any]]
    observation_summary: str
    observed_at: datetime
    evaluated_at: datetime
    confidence: float | None
    limitations: list[dict[str, Any]]
    contradicts_observation_id: UUID | None
    corrects_observation_id: UUID | None
    schema_version: int
    created_at: datetime


class NeedRevisionRead(BaseModel):
    need_id: str
    revision_id: UUID
    revision: int
    tenant_id: str
    previous_revision_id: UUID | None
    origin: str
    status: str
    subject_references: list[dict[str, Any]]
    objective_reference: dict[str, Any] | None
    condition_summary: str
    uncertainty: list[dict[str, Any]]
    priority: dict[str, Any] | None
    confidence: float | None
    observation_references: list[dict[str, Any]]
    related_need_references: list[dict[str, Any]]
    candidate_responses: list[dict[str, Any]]
    proposal_references: list[dict[str, Any]]
    mission_references: list[dict[str, Any]]
    impact_assessment: dict[str, Any] | None
    resolution_observation_references: list[dict[str, Any]]
    producer: str
    schema_version: int
    created_at: datetime
    grants_execution_authority: Literal[False] = False


class ObservationListRead(BaseModel):
    observations: list[ObservationRead]


class MeasurementRead(BaseModel):
    measurement_id: UUID
    tenant_id: str
    source_kind: str
    source_version: str
    source_content_fingerprint: str
    recognized_need_id: str | None = None


class NeedListRead(BaseModel):
    needs: list[NeedRevisionRead]


def _observation_read(row: BusinessObservation) -> ObservationRead:
    return ObservationRead(
        observation_id=row.id,
        tenant_id=row.tenant_id,
        source_kind=row.source_kind,
        source_reference=dict(row.source_reference),
        source_fingerprint=row.source_fingerprint,
        producer=row.producer,
        subject_references=list(row.subject_references),
        observation_summary=row.observation_summary,
        observed_at=row.observed_at,
        evaluated_at=row.evaluated_at,
        confidence=row.confidence,
        limitations=list(row.limitations),
        contradicts_observation_id=row.contradicts_observation_id,
        corrects_observation_id=row.corrects_observation_id,
        schema_version=row.schema_version,
        created_at=row.created_at,
    )


def _need_read(row: BusinessNeedRevision) -> NeedRevisionRead:
    return NeedRevisionRead(
        need_id=row.need_id,
        revision_id=row.id,
        revision=row.revision,
        tenant_id=row.tenant_id,
        previous_revision_id=row.previous_revision_id,
        origin=row.origin,
        status=row.status,
        subject_references=list(row.subject_references),
        objective_reference=dict(row.objective_reference) if row.objective_reference is not None else None,
        condition_summary=row.condition_summary,
        uncertainty=list(row.uncertainty),
        priority=dict(row.priority) if row.priority is not None else None,
        confidence=row.confidence,
        observation_references=list(row.observation_references),
        related_need_references=list(row.related_need_references),
        candidate_responses=list(row.candidate_responses),
        proposal_references=list(row.proposal_references),
        mission_references=list(row.mission_references),
        impact_assessment=dict(row.impact_assessment) if row.impact_assessment is not None else None,
        resolution_observation_references=list(row.resolution_observation_references),
        producer=row.producer,
        schema_version=row.schema_version,
        created_at=row.created_at,
    )


def _record_observation(
    *, service: BusinessUnderstandingService, tenant_id: str, body: ObservationCreate, producer: str
) -> BusinessObservation:
    return service.record_observation(
        tenant_id=tenant_id,
        source=SourceReference(source_kind=body.source_kind, reference=body.source_reference),
        observation_summary=body.observation_summary,
        subject_references=body.subject_references,
        observed_at=body.observed_at,
        confidence=body.confidence,
        limitations=body.limitations,
        contradicts_observation_id=body.contradicts_observation_id,
        corrects_observation_id=body.corrects_observation_id,
        producer=producer,
    )


def _append_need(
    *, service: BusinessUnderstandingService, tenant_id: str, body: NeedRevisionCreate, producer: str
) -> BusinessNeedRevision:
    return service.append_need_revision(
        tenant_id=tenant_id,
        need_id=body.need_id,
        expected_revision=body.expected_revision,
        origin=body.origin,
        status=body.status,
        subject_references=body.subject_references,
        objective_reference=body.objective_reference,
        condition_summary=body.condition_summary,
        uncertainty=body.uncertainty,
        priority=body.priority,
        confidence=body.confidence,
        observation_ids=body.observation_ids,
        related_need_references=body.related_need_references,
        candidate_responses=body.candidate_responses,
        proposal_references=body.proposal_references,
        mission_references=body.mission_references,
        impact_assessment=body.impact_assessment,
        resolution_observation_ids=body.resolution_observation_ids,
        producer=producer,
    )


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BusinessNeedRevisionConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "BUSINESS_NEED_REVISION_CONFLICT", "current_revision": exc.current_revision},
        )
    if isinstance(exc, (BusinessUnderstandingValidationError, IntegrityError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": "BUSINESS_UNDERSTANDING_INVALID"}
        )
    raise exc


@router.post("/observations", response_model=ObservationRead, status_code=status.HTTP_201_CREATED)
def create_observation(
    body: ObservationCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ObservationRead:
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_MANAGE, tenant_id=tenant_id
    )
    try:
        return _observation_read(
            _record_observation(
                service=BusinessUnderstandingService(db),
                tenant_id=str(tenant_id),
                body=body,
                producer=_actor_id(request),
            )
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/measurements", response_model=MeasurementRead, status_code=status.HTTP_201_CREATED)
def ingest_measurement(
    body: MeasurementCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MeasurementRead:
    """Authenticated customer-attested operating measurement ingress."""
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_MANAGE, tenant_id=tenant_id
    )
    if body.source_kind == "source_verified":
        raise HTTPException(status_code=422, detail="source_verified measurements require an internal adapter")
    if any(k.goal_id != body.goal.goal_id for k in body.kpis):
        raise HTTPException(status_code=422, detail="all KPI values must belong to the supplied goal")
    if body.measurement_period_start and body.measurement_period_end:
        if body.measurement_period_end < body.measurement_period_start:
            raise HTTPException(status_code=422, detail="measurement period is invalid")
    try:
        measurement, need = BusinessUnderstandingService(db).ingest_measurement(
            tenant_id=str(tenant_id),
            goal=body.goal,
            kpis=body.kpis,
            subject_references=body.subject_references,
            source_kind=body.source_kind,
            source_reference=body.source_reference,
            source_version=body.source_version,
            measurement_period_start=body.measurement_period_start,
            measurement_period_end=body.measurement_period_end,
            observed_at=body.observed_at,
            limitations=body.limitations,
            confidence=body.confidence,
            producer=_actor_id(request),
        )
        return MeasurementRead(
            measurement_id=measurement.id,
            tenant_id=measurement.tenant_id,
            source_kind=measurement.source_kind,
            source_version=measurement.source_version,
            source_content_fingerprint=measurement.source_content_fingerprint,
            recognized_need_id=need.need_id if need is not None else None,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/needs", response_model=NeedRevisionRead, status_code=status.HTTP_201_CREATED)
def create_or_revise_need(
    body: NeedRevisionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> NeedRevisionRead:
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_MANAGE, tenant_id=tenant_id
    )
    try:
        return _need_read(
            _append_need(
                service=BusinessUnderstandingService(db),
                tenant_id=str(tenant_id),
                body=body,
                producer=_actor_id(request),
            )
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/recognitions", response_model=NeedRevisionRead, status_code=status.HTTP_201_CREATED)
def create_recognition(
    body: RecognitionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> NeedRevisionRead:
    """Atomically persist the observed condition and its initial need hypothesis."""
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_MANAGE, tenant_id=tenant_id
    )
    service = BusinessUnderstandingService(db)
    try:
        producer = _actor_id(request)
        observation = _record_observation(
            service=service,
            tenant_id=str(tenant_id),
            body=body.observation,
            producer=producer,
        )
        need_body = body.need.model_copy(update={"observation_ids": [observation.id]})
        return _need_read(_append_need(service=service, tenant_id=str(tenant_id), body=need_body, producer=producer))
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/needs/{need_id}/revisions/{revision}/assessments",
    response_model=BusinessNeedAssessmentResult,
    status_code=status.HTTP_201_CREATED,
)
def assess_need(
    need_id: str,
    revision: int,
    body: NeedAssessmentRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> BusinessNeedAssessmentResult:
    """Assess a need using ontology rules; it cannot create or authorize work."""

    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_MANAGE, tenant_id=tenant_id
    )
    try:
        return BusinessNeedReasoningService(BusinessUnderstandingRepository(db)).assess(
            tenant_id=str(tenant_id),
            need_id=need_id,
            revision=revision,
            request=body,
            producer=_actor_id(request),
        )
    except ValueError as exc:
        raise _map_error(BusinessUnderstandingValidationError("assessment is invalid")) from exc


@router.get("/observations", response_model=ObservationListRead)
def list_observations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ObservationListRead:
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_READ, tenant_id=tenant_id
    )
    rows = BusinessUnderstandingRepository(db).list_observations_for_tenant(tenant_id=str(tenant_id), limit=limit)
    return ObservationListRead(observations=[_observation_read(row) for row in rows])


@router.get("/needs", response_model=NeedListRead)
def list_needs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> NeedListRead:
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_READ, tenant_id=tenant_id
    )
    rows = BusinessUnderstandingRepository(db).list_latest_needs_for_tenant(tenant_id=str(tenant_id), limit=limit)
    return NeedListRead(needs=[_need_read(row) for row in rows])


@router.get("/needs/{need_id}", response_model=NeedRevisionRead)
def read_need(
    need_id: str,
    request: Request,
    revision: int | None = Query(default=None, ge=1),
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> NeedRevisionRead:
    require_route_permission(
        request=request, db=db, permission=Permission.BUSINESS_UNDERSTANDING_READ, tenant_id=tenant_id
    )
    repository = BusinessUnderstandingRepository(db)
    row = (
        repository.get_need_revision_for_tenant(tenant_id=str(tenant_id), need_id=need_id, revision=revision)
        if revision is not None
        else repository.get_latest_need_for_tenant(tenant_id=str(tenant_id), need_id=need_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="business need not found for tenant")
    return _need_read(row)
