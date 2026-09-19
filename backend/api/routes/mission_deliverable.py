"""Tenant-scoped read API for the assembled RevOps mission deliverable."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.services.document_artifacts import read_artifact
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.revops_deliverable import (
    RevOpsMissionDeliverableRead,
    assemble_revops_mission_deliverable,
)
from backend.services.mission_runtime_evidence_projection import (
    MissionRuntimeEvidenceProjection,
    build_mission_runtime_evidence_projection,
)

router = APIRouter(prefix="/missions", tags=["missions"])


def _draft_artifact_ids(tasks: list[ExecutionTask]) -> tuple[str, ...]:
    """Return stable draft IDs from the canonical completed draft artifact."""

    artifacts = collect_materialized_artifacts(tasks)
    drafts = next(
        (artifact for artifact in artifacts if artifact.artifact_key == "introduction_drafts"),
        None,
    )
    if drafts is None or not isinstance(drafts.payload, list):
        return ()
    artifact_ids: list[str] = []
    for row in drafts.payload:
        if not isinstance(row, dict):
            continue
        artifact_id = row.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id.strip() and artifact_id.strip() not in artifact_ids:
            artifact_ids.append(artifact_id.strip())
    return tuple(artifact_ids)


@router.get("/{mission_id}/deliverable", response_model=RevOpsMissionDeliverableRead)
def read_revops_mission_deliverable(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RevOpsMissionDeliverableRead:
    """Assemble the current artifact-backed RevOps report without runtime mutation."""

    _ = request
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    tasks = ExecutionTaskRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    document_artifacts = {}
    for artifact_id in _draft_artifact_ids(tasks):
        artifact = read_artifact(db, tenant_id=tenant_scope, artifact_id=artifact_id)
        if artifact is not None:
            document_artifacts[artifact_id] = artifact

    evidence = EvidenceRepository(db).list_for_mission(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    reviews = OutcomeReviewRepository(db).list_for_mission(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    try:
        return assemble_revops_mission_deliverable(
            mission=mission,
            tasks=tasks,
            document_artifacts=document_artifacts,
            evidence_records=evidence,
            outcome_reviews=reviews,
        )
    except (ValidationError, ValueError) as exc:
        if str(exc) == "mission deliverable runtime state is absent":
            raise HTTPException(status_code=404, detail="mission deliverable runtime state not found") from exc
        raise HTTPException(status_code=409, detail="mission deliverable assembly is invalid") from exc


@router.get("/{mission_id}/runtime-evidence", response_model=MissionRuntimeEvidenceProjection)
def read_mission_runtime_evidence(
    mission_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRuntimeEvidenceProjection:
    """Expose persisted runtime facts for GRAFT review without executing work."""

    tenant_scope = str(tenant_id)
    require_route_permission(request=request, db=db, permission=Permission.RUNTIME_VIEW, tenant_id=tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    tasks = ExecutionTaskRepository(db).list_for_mission_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    task_ids = [task.id for task in tasks]
    leases = (
        list(
            db.scalars(
                select(WorkerLease).where(WorkerLease.tenant_id == tenant_scope, WorkerLease.task_id.in_(task_ids))
            )
        )
        if task_ids
        else []
    )
    lineage = LineageRecordRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    evidence = EvidenceRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    audit_events = AuditEventRepository(db).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_scope,
    )
    return build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_scope,
        mission_status=mission.status,
        mission_metadata=mission.metadata_json if isinstance(mission.metadata_json, dict) else {},
        tasks=tasks,
        leases=leases,
        lineage=lineage,
        evidence=evidence,
        audit_events=audit_events,
    )
