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
from backend.services.business_profile.company_introduction import CompanyIntroductionDraft
from backend.services.mission_composition.deliverable_completion import validate_materialized_artifact
from backend.services.mission_composition.deliverable_runtime_artifacts import (
    collect_materialized_artifacts,
    declared_artifact_key,
    materialized_artifact_for_task,
)


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
    company_introduction_draft: CompanyIntroductionDraft | None = None
    missing_fields: tuple[str, ...] = ()
    conflicting_fields: tuple[str, ...] = ()
    artifacts: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: tuple[uuid.UUID, ...] = ()
    profile_source_evidence_ids: tuple[uuid.UUID, ...] = ()
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
        if artifact.artifact_key in {"business_profile_facts", "business_review_report"}
        and (artifact.artifact_key != "business_review_report" or validate_materialized_artifact(artifact).valid)
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

    # A mission can contain evidence from several tasks. Only identify a record
    # as the profile source when it belongs to a completed producer of this
    # exact artifact and contains the same approved-profile payload.
    profile_task_ids = {
        task.id
        for task in tasks
        if (artifact := materialized_artifact_for_task(task)) is not None
        and artifact.artifact_key == "business_profile_facts"
        and artifact.payload == payload
    }
    profile_source_evidence_ids = tuple(
        evidence.id
        for evidence in evidence_records
        if evidence.execution_task_id in profile_task_ids
        and evidence.collection_status == "collected"
        and isinstance(evidence.structured_payload, dict)
        and evidence.structured_payload.get("business_profile_facts") == payload
        and payload.get("source") == "approved_business_profile"
        and profile_id is not None
    )

    status_counts = Counter(str(task.status) for task in tasks)
    review_required = any(declared_artifact_key(task) == "business_review_report" for task in tasks)
    complete = (
        bool(tasks)
        and all(str(task.status) == "completed" for task in tasks)
        and (not review_required or "business_review_report" in artifacts)
    )
    return ProfileDeliverableRead(
        mission_id=mission.id,
        objective=mission.objective,
        profile_id=profile_id,
        approved_facts=approved_facts,
        profile_brief=profile_brief,
        company_introduction_draft=payload.get("company_introduction_draft"),
        missing_fields=tuple(str(value) for value in profile_brief.get("missing_fields", ()) if value),
        conflicting_fields=tuple(str(value) for value in profile_brief.get("conflicting_fields", ()) if value),
        artifacts=artifacts,
        evidence_ids=tuple(evidence.id for evidence in evidence_records),
        profile_source_evidence_ids=profile_source_evidence_ids,
        task_statuses=dict(sorted(status_counts.items())),
        complete=complete,
    )
