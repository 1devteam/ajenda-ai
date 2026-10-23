"""Tenant-bound observations and append-only business-need hypotheses.

These records deliberately preserve *interpretation about* business state.
They do not replace the profile, CRM, financial, evidence, or knowledge
systems that own the underlying facts.  They also cannot authorize work.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base

BUSINESS_UNDERSTANDING_SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(UTC)


class BusinessObservation(Base):
    """An attributed observation, not a replacement business-state record."""

    __tablename__ = "business_observations"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_observations_confidence",
        ),
        CheckConstraint(
            "source_kind IN ('business_profile', 'tenant_internal_record', 'evidence', "
            "'outcome_review', 'knowledge_artifact', 'external_provider', 'customer_instruction')",
            name="ck_business_observations_source_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    source_reference: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    producer: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    observation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    limitations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    contradicts_observation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    corrects_observation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=BUSINESS_UNDERSTANDING_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BusinessNeedRevision(Base):
    """Immutable revision of a business need hypothesis.

    ``need_id`` is stable across revisions.  A revision may recommend candidate
    responses, but it is declarative and has no task, queue, provider, or
    authorization relationship.
    """

    __tablename__ = "business_need_revisions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_business_need_revisions_tenant_id"),
        UniqueConstraint("tenant_id", "need_id", "revision", name="uq_business_need_revisions_tenant_need_revision"),
        ForeignKeyConstraint(
            ["tenant_id", "previous_revision_id"],
            ["business_need_revisions.tenant_id", "business_need_revisions.id"],
            name="fk_business_need_revisions_previous_tenant",
        ),
        CheckConstraint(
            "status IN ('recognized', 'monitoring', 'challenged', 'response_proposed', "
            "'impact_monitored', 'resolved', 'disproven', 'superseded')",
            name="ck_business_need_revisions_status",
        ),
        CheckConstraint(
            "origin IN ('explicitly_stated', 'observed', 'inferred')",
            name="ck_business_need_revisions_origin",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_business_need_revisions_confidence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    need_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="recognized")
    subject_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    objective_reference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    condition_summary: Mapped[str] = mapped_column(Text, nullable=False)
    uncertainty: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    priority: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    observation_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    related_need_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    candidate_responses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    proposal_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    mission_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    impact_assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    resolution_observation_references: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    producer: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=BUSINESS_UNDERSTANDING_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BusinessNeedAssessment(Base):
    """Immutable reasoning result about one tenant-owned need revision.

    This preserves an assessment's inputs and conclusion without redefining a
    source fact, selecting runtime actions, or changing the need itself.
    """

    __tablename__ = "business_need_assessments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_business_need_assessments_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "need_revision_id"],
            ["business_need_revisions.tenant_id", "business_need_revisions.id"],
            name="fk_business_need_assessments_need_revision_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    need_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    need_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    need_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assessment_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    producer: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=BUSINESS_UNDERSTANDING_SCHEMA_VERSION)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
