"""Assemble the durable read model for approved business-profile missions.

This projection is read-only and artifact-backed. It does not reinterpret the
mission, execute retrieval, mutate profile truth, or grant runtime authority.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts


class ProfileDeliverableRead(BaseModel):
    """Tenant-scoped, typed profile brief assembled from a completed artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["business_profile_brief"] = "business_profile_brief"
    mission_id: uuid.UUID
    objective: str
    profile_id: uuid.UUID | None = None
    approved_facts: dict[str, Any] = Field(default_factory=dict)
    profile_brief: dict[str, Any] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    conflicting_fields: tuple[str, ...] = ()
    artifacts: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[uuid.UUID, ...] = ()
    task_statuses: dict[str, int] = Field(default_factory=dict)
    complete: bool = False
    grants_execution_authority: Literal[False] = False


def assemble_profile_deliverable(
    *,
    mission: Mission,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord] = (),
) -> ProfileDeliverableRead:
    """Build a profile deliverable only from tenant-owned completed task output."""

    tenant_id = str(mission.tenant_id)
    for task in tasks:
        if str(task.tenant_id) != tenant_id or task.mission_id != mission.id:
            raise ValueError("profile deliverable task ownership mismatch")
    for evidence in evidence_records:
        if str(evidence.tenant_id) != tenant_id or evidence.mission_id != mission.id:
            raise ValueError("profile deliverable evidence ownership mismatch")

    artifacts = {
        artifact.artifact_key: artifact.payload
        for artifact in collect_materialized_artifacts(list(tasks))
        if artifact.artifact_key == "business_profile_facts"
    }
    payload = artifacts.get("business_profile_facts")
    if not isinstance(payload, dict):
        raise ValueError("business profile deliverable artifact is absent")
    profile_brief = payload.get("profile_brief")
    approved_facts = payload.get("approved_facts")
    if not isinstance(profile_brief, dict) or not isinstance(approved_facts, dict):
        raise ValueError("business profile deliverable artifact is invalid")

    raw_profile_id = payload.get("profile_id")
    try:
        profile_id = uuid.UUID(str(raw_profile_id)) if raw_profile_id else None
    except (TypeError, ValueError) as exc:
        raise ValueError("business profile deliverable profile_id is invalid") from exc

    status_counts = Counter(str(task.status) for task in tasks)
    complete = bool(tasks) and all(str(task.status) == "completed" for task in tasks)
    return ProfileDeliverableRead(
        mission_id=mission.id,
        objective=mission.objective,
        profile_id=profile_id,
        approved_facts=approved_facts,
        profile_brief=profile_brief,
        missing_fields=tuple(str(value) for value in profile_brief.get("missing_fields", ()) if value),
        conflicting_fields=tuple(str(value) for value in profile_brief.get("conflicting_fields", ()) if value),
        artifacts=artifacts,
        evidence_ids=tuple(evidence.id for evidence in evidence_records),
        task_statuses=dict(sorted(status_counts.items())),
        complete=complete,
    )
