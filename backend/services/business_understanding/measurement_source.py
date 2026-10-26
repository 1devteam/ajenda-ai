"""Internal measurement adapter for canonical, tenant-owned source reads.

This module proves what a runtime record.read actually observed. It deliberately
does NOT independently verify the commercial truth of tenant-authored KPI values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from backend.repositories.evidence_repository import EvidenceRepository
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.evidence_lineage import EvidenceLineageResolution
from backend.services.ontology.types import BusinessObjectType
from backend.services.tools.evidence_bridge import require_canonical_source_observation_evidence

_MEASUREMENT_RECORD_TYPES: frozenset[str] = frozenset({"account", "contact", "opportunity"})


class RuntimeMeasurementSnapshot(BaseModel):
    """Explicit source-declared measurement contract recorded inside a tenant row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    goal: Goal
    kpis: tuple[Kpi, ...] = Field(min_length=1, max_length=100)
    source_version: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    measurement_period_start: datetime | None = None
    measurement_period_end: datetime | None = None
    successor_mission_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_consistent_snapshot(self) -> RuntimeMeasurementSnapshot:
        if not self.goal.subject_refs:
            raise ValueError("source measurement must declare at least one business subject")
        ids = [item.kpi_id for item in self.kpis]
        if len(ids) != len(set(ids)):
            raise ValueError("source measurement KPI identities must be unique")
        if any(item.goal_id != self.goal.goal_id for item in self.kpis):
            raise ValueError("source measurement KPI does not belong to the declared goal")
        timestamps = (self.observed_at, self.measurement_period_start, self.measurement_period_end)
        if any(item is not None and (item.tzinfo is None or item.utcoffset() is None) for item in timestamps):
            raise ValueError("source measurement timestamps must include timezone")
        if self.measurement_period_start and self.measurement_period_end:
            if self.measurement_period_end < self.measurement_period_start:
                raise ValueError("source measurement period is reversed")
        if self.measurement_period_end and self.observed_at < self.measurement_period_end:
            raise ValueError("source measurement predates the end of its period")
        return self


@dataclass(frozen=True, slots=True)
class RuntimeVerifiedMeasurement:
    """Exact runtime projection and its bounded source-identity authority."""

    snapshot: RuntimeMeasurementSnapshot
    evidence_id: uuid.UUID
    tenant_id: str
    source_reference: dict[str, str]
    record_type: str
    record_id: str

    @property
    def limitations(self) -> list[dict[str, str]]:
        return [
            {"code": "source_read_proved_not_kpi_truth"},
            {"code": "tenant_internal_record_can_be_customer_authored"},
            {"code": "source_independence_not_established"},
        ]


def resolve_runtime_measurement(
    *, session: Session, tenant_id: str, evidence_id: uuid.UUID
) -> RuntimeVerifiedMeasurement:
    """Fail closed on foreign, forged, absent, or semantically unrelated source reads."""

    evidence = EvidenceRepository(session).get_for_tenant(tenant_id=tenant_id, evidence_id=evidence_id)
    if evidence is None:
        raise ValueError("source measurement evidence is inaccessible for tenant")
    if evidence.evidence_source != "tool.invoke.record.read":
        raise ValueError("source measurement requires a canonical record.read owner")
    item = require_canonical_source_observation_evidence(session=session, record=evidence)
    if item.action_name != "record.read" or item.tool_provider != "local_records":
        raise ValueError("source measurement requires internal record.read evidence")
    lineage = item.lineage
    if (
        lineage is None
        or lineage.resolution != EvidenceLineageResolution.KNOWN
        or lineage.source_identity is None
        or lineage.source_identity.source_system != "tenant_record_store"
    ):
        raise ValueError("source measurement requires resolved tenant-record identity")

    payload: dict[str, Any] = item.structured_payload
    record_type = payload.get("record_type")
    record = payload.get("record")
    if record_type not in _MEASUREMENT_RECORD_TYPES or payload.get("found") is not True:
        raise ValueError("source measurement requires an existing supported record")
    if not isinstance(record, dict) or not isinstance(record.get("id"), str):
        raise ValueError("source measurement record identity is absent")
    record_id = record["id"]
    if lineage.source_identity.source_record_id != f"{record_type}:{record_id}":
        raise ValueError("source measurement runtime record identity disagrees")
    if item.records_inspected != [record_id]:
        raise ValueError("source measurement inspection lineage does not match the record")
    if not isinstance(record.get("operating_measurement"), dict):
        raise ValueError("source record has no explicit operating_measurement snapshot")
    snapshot = RuntimeMeasurementSnapshot.model_validate(record["operating_measurement"])
    if snapshot.observed_at > evidence.created_at:
        raise ValueError("source measurement observed_at is later than canonical source read")
    expected_type = BusinessObjectType(record_type)
    if {(subject.object_type, subject.object_id) for subject in snapshot.goal.subject_refs} != {
        (expected_type, record_id)
    }:
        raise ValueError("source measurement must be scoped to the exact read record identity")
    return RuntimeVerifiedMeasurement(
        snapshot=snapshot,
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        source_reference={
            "evidence_id": str(evidence_id),
            "source_system": "tenant_record_store",
            "record_type": record_type,
            "record_id": record_id,
        },
        record_type=record_type,
        record_id=record_id,
    )
