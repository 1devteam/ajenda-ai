"""Independent recurring runtime assurance.

This service observes canonical mission/runtime state and appends assurance-only
history. It never mutates missions, tasks, leases, business facts, credentials,
queue state, approvals, providers, or runtime authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.assurance_snapshot import AssuranceSnapshot
from backend.domain.audit_event import AuditEvent
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.worker_lease import WorkerLease
from backend.repositories.assurance_snapshot_repository import AssuranceSnapshotRepository
from backend.services.mission_composition.deliverable_runtime_observability import build_deliverable_runtime_state_read
from backend.services.mission_runtime_evidence_projection import build_mission_runtime_evidence_projection


_STATUS_RANK = {
    "aligned": 0,
    "incomplete": 1,
    "drifted": 2,
    "contradictory": 3,
}


class ContinuousAssuranceService:
    """Read runtime truth and persist only assurance observations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._snapshots = AssuranceSnapshotRepository(session)

    def run_tenant(self, *, tenant_id: str, mission_limit: int = 200) -> list[AssuranceSnapshot]:
        # Deliberately avoid MissionRepository.list_by_tenant(): that method may
        # reconcile review holds and mutate mission status. Assurance observation
        # must not alter runtime or business state.
        missions = list(
            self._session.scalars(
                select(Mission)
                .where(Mission.tenant_id == tenant_id)
                .order_by(Mission.created_at.desc())
                .limit(max(1, min(mission_limit, 500)))
            )
        )
        return [self.reconcile_mission(tenant_id=tenant_id, mission=mission) for mission in missions]

    def reconcile_mission(self, *, tenant_id: str, mission: Mission) -> AssuranceSnapshot:
        if mission.tenant_id != tenant_id:
            raise ValueError("mission does not belong to assurance tenant")

        tasks = list(
            self._session.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_id,
                    ExecutionTask.mission_id == mission.id,
                )
            )
        )
        task_ids = [task.id for task in tasks]
        leases = (
            list(
                self._session.scalars(
                    select(WorkerLease).where(
                        WorkerLease.tenant_id == tenant_id,
                        WorkerLease.task_id.in_(task_ids),
                    )
                )
            )
            if task_ids
            else []
        )
        lineage = list(
            self._session.scalars(
                select(LineageRecord).where(
                    LineageRecord.tenant_id == tenant_id,
                    LineageRecord.mission_id == mission.id,
                )
            )
        )
        evidence = list(
            self._session.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_id,
                    EvidenceRecord.mission_id == mission.id,
                )
            )
        )
        audits = list(
            self._session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.mission_id == mission.id,
                )
            )
        )

        runtime = build_mission_runtime_evidence_projection(
            mission_id=mission.id,
            tenant_id=tenant_id,
            mission_status=mission.status,
            mission_metadata=mission.metadata_json if isinstance(mission.metadata_json, dict) else {},
            tasks=tasks,
            leases=leases,
            lineage=lineage,
            evidence=evidence,
            audit_events=audits,
        )
        runtime_state_error: str | None = None
        try:
            runtime_state = build_deliverable_runtime_state_read(mission.metadata_json)
        except ValueError as exc:
            runtime_state = None
            runtime_state_error = str(exc)

        findings: list[dict[str, Any]] = []
        if runtime_state_error is not None:
            findings.append(
                {
                    "category": "runtime_state_invalid",
                    "code": runtime_state_error[:500],
                    "severity": "error",
                }
            )
        for code in runtime.contradictions:
            findings.append({"category": "runtime_contradiction", "code": code, "severity": "error"})
        for code in runtime.missing_evidence:
            findings.append({"category": "missing_evidence", "code": code, "severity": "warning"})

        reconciliation_status = "not_available"
        semantic_status = "not_available"
        epistemic_confidence: float | None = None
        lifecycle_state = "not_available"
        if runtime_state is not None:
            lifecycle_state = runtime_state.lifecycle_state
            epistemic_confidence = runtime_state.epistemic_confidence
            if runtime_state.contradiction_codes:
                for code in runtime_state.contradiction_codes:
                    findings.append({"category": "artifact_contradiction", "code": code, "severity": "error"})
            if runtime_state.runtime_reconciliation is not None:
                reconciliation_status = runtime_state.runtime_reconciliation.status
                semantic_status = runtime_state.runtime_reconciliation.semantic_status
                for code in runtime_state.runtime_reconciliation.semantic_mismatch_codes:
                    findings.append({"category": "semantic_contradiction", "code": code, "severity": "error"})
                for code in runtime_state.runtime_reconciliation.semantic_drift_codes:
                    findings.append({"category": "semantic_drift", "code": code, "severity": "warning"})

        status = self._status(
            runtime_contradictions=bool(runtime.contradictions) or runtime_state_error is not None,
            missing_evidence=bool(runtime.missing_evidence),
            reconciliation_status=reconciliation_status,
            lifecycle_state=lifecycle_state,
        )
        calibration_eligible = (
            epistemic_confidence is not None
            and mission.status in {"completed", "failed", "blocked", "cancelled", "dead_lettered"}
            and reconciliation_status != "not_available"
        )
        calibration_outcome_aligned = status == "aligned" if calibration_eligible else None

        observation_payload = {
            "status": status,
            "first_divergence": runtime.first_divergence,
            "findings": findings,
            "runtime_summary": {
                "mission_status": runtime.mission_status,
                "node_count": len(runtime.nodes),
                "edge_count": len(runtime.edges),
                "contradiction_count": len(runtime.contradictions),
                "missing_evidence_count": len(runtime.missing_evidence),
                "task_flow_count": len(runtime.task_flows),
                "record_flow_count": len(runtime.record_flows),
            },
            "reconciliation_summary": {
                "runtime_reconciliation": reconciliation_status,
                "semantic_reconciliation": semantic_status,
                "lifecycle_state": lifecycle_state,
            },
            "epistemic_confidence": epistemic_confidence,
            "calibration_eligible": calibration_eligible,
            "calibration_outcome_aligned": calibration_outcome_aligned,
        }
        fingerprint = "sha256:" + hashlib.sha256(
            json.dumps(observation_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        latest = self._snapshots.latest_for_mission(tenant_id=tenant_id, mission_id=mission.id)
        if latest is not None and latest.observation_fingerprint == fingerprint:
            return latest

        snapshot = AssuranceSnapshot(
            tenant_id=tenant_id,
            mission_id=mission.id,
            status=status,
            observation_fingerprint=fingerprint,
            first_divergence=runtime.first_divergence,
            finding_count=len(findings),
            findings=findings,
            runtime_summary=observation_payload["runtime_summary"],
            reconciliation_summary=observation_payload["reconciliation_summary"],
            epistemic_confidence=epistemic_confidence,
            calibration_eligible=calibration_eligible,
            calibration_outcome_aligned=calibration_outcome_aligned,
            authority_class="read_model",
            grants_execution_authority=False,
        )
        return self._snapshots.append(snapshot)

    @staticmethod
    def _status(
        *,
        runtime_contradictions: bool,
        missing_evidence: bool,
        reconciliation_status: str,
        lifecycle_state: str,
    ) -> str:
        candidates = ["aligned"]
        if missing_evidence or reconciliation_status in {"incomplete", "not_run"}:
            candidates.append("incomplete")
        if reconciliation_status == "drifted":
            candidates.append("drifted")
        if runtime_contradictions or reconciliation_status in {"contradictory", "blocked"}:
            candidates.append("contradictory")
        if lifecycle_state == "contradictory":
            candidates.append("contradictory")
        return max(candidates, key=lambda value: _STATUS_RANK[value])
