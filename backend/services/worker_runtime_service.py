from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, MissionState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueAdapter
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.worker_lease_repository import WorkerLeaseRepository
from backend.runtime.transitions import transition_lease, transition_mission, transition_task
from backend.services.mission_intake_quality import contains_composition_clarification
from backend.services.runtime_evidence_ledger import RuntimeCausalObservation, RuntimeEvidenceLedger
from backend.services.runtime_information_observation import describe_information
from backend.services.runtime_queue_dispatcher import RuntimeQueueDispatchService
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records
from backend.services.tools.mission_input_binding import pending_dependency_keys
from backend.services.worker_runtime_contracts import (
    _TERMINAL_TASK_STATES,
    _failure_evidence_record,
    _materialized_artifact_reference,
    _mirror_task_output_to_metadata,
    _validate_declared_output_contract,
)
from backend.services.worker_runtime_outcome_review import (
    create_draft_outcome_review as _create_draft_outcome_review_impl,
)
from backend.services.worker_runtime_outcome_review import (
    gtm_side_effect_was_real as _gtm_side_effect_was_real_impl,
)
from backend.services.worker_runtime_outcome_review import (
    is_high_risk_gtm_side_effect as _is_high_risk_gtm_side_effect_impl,
)
from backend.services.worker_runtime_queue_reconciliation import (
    assert_current_releasable_claim as _assert_current_releasable_claim_impl,
)
from backend.services.worker_runtime_queue_reconciliation import (
    assert_no_active_lease as _assert_no_active_lease_impl,
)
from backend.services.worker_runtime_queue_reconciliation import (
    reconcile_claimed_terminal_queue_artifact as _reconcile_claimed_terminal_queue_artifact_impl,
)
from backend.services.worker_runtime_queue_reconciliation import (
    record_terminal_queue_cleanup_failure as _record_terminal_queue_cleanup_failure_impl,
)
from backend.services.worker_runtime_queue_reconciliation import (
    transition_lease_to_released as _transition_lease_to_released_impl,
)
from backend.services.worker_runtime_rollup import (
    maybe_rollup_mission_status as _maybe_rollup_mission_status_impl,
)
from backend.services.worker_runtime_rollup import (
    refresh_deliverable_completion_read_model as _refresh_deliverable_completion_read_model_impl,
)

logger = logging.getLogger("ajenda.worker_runtime_service")


_QUEUE_PAYLOAD_DB_VISIBILITY_GRACE_SECONDS = 30.0


def _causal_observation_for_tool_output(
    *, task: ExecutionTask, task_output: dict[str, Any]
) -> tuple[RuntimeCausalObservation, ...]:
    """Extract bounded tool/source decisions without copying provider values."""

    action = task_output.get("action")
    if not isinstance(action, str):
        return ()
    output = task_output.get("output")
    output = output if isinstance(output, dict) else {}
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    invocation = invocation if isinstance(invocation, dict) else {}
    input_value = invocation.get("input")
    input_value = input_value if isinstance(input_value, dict) else {}
    safe_names = (
        "include_public_search",
        "local_fixture_only",
        "exclude_internal_records",
        "public_search_real",
        "web_result_count",
        "internal_count",
        "prospect_count",
        "verified_public_candidate_count",
        "rejected_public_candidates",
        "source",
        "access_mode",
        "business_context_source",
        "research_gap",
    )
    safe_metadata = {name: output[name] for name in safe_names if name in output}
    for name in (
        "include_public_search",
        "local_fixture_only",
        "exclude_internal_records",
        "binding_required",
        "collect_contacts",
    ):
        if name in input_value:
            safe_metadata[f"input_{name}"] = input_value[name]
    partitions = output.get("source_partitions")
    source_provenance: dict[str, str] = {}
    if isinstance(partitions, dict):
        for name, value in partitions.items():
            if isinstance(value, dict):
                source_provenance[str(name)] = ";".join(
                    f"{key}={value[key]}"
                    for key in ("candidate_count", "result_count", "provider_observed")
                    if key in value
                )
    source = str(output.get("source") or output.get("access_mode") or "unknown")
    public_only = bool(input_value.get("exclude_internal_records"))
    common: dict[str, Any] = {
        "reason_code": "public_only_research" if public_only else "tool_invocation",
        "selected_path": source,
        "source_provenance": source_provenance,
        "field_lineage": {
            "tool.input.include_public_search": "mission.constraints.public_source_scope",
            "tool.input.local_fixture_only": "mission.constraints.fixture_scope",
            "tool.output.source": "provider_or_record_source",
        },
        "constraints": ("public_only",) if public_only else (),
        "safe_metadata": safe_metadata,
    }
    observations = [
        RuntimeCausalObservation(
            stage="tool_output",
            decision="provider_output_classified",
            transformation_id=f"tool:{action}:output:v1",
            **common,
        )
    ]
    if source_provenance:
        observations.append(
            RuntimeCausalObservation(
                stage="source_partition",
                decision="information_source_classified",
                reason_code="source_partition_observed",
                transformation_id=f"tool:{action}:source-partition:v1",
                selected_path=source,
                source_provenance=source_provenance,
                constraints=("public_only",) if public_only else (),
                safe_metadata=safe_metadata,
            )
        )
    return tuple(observations)


class WorkerRuntimeService:
    def __init__(self, session: Session, queue: QueueAdapter) -> None:
        self._session = session
        self._queue = queue
        self._tasks = ExecutionTaskRepository(session)
        self._leases = WorkerLeaseRepository(session)
        self._audit = AuditEventRepository(session)
        self._evidence_ledger = RuntimeEvidenceLedger(session, audit_repository=self._audit, flush=False)
        self._dispatches = RuntimeQueueDispatchService(session, queue)

    def _append_task_causal_observations(
        self,
        *,
        task: ExecutionTask,
        worker_id: str,
        lease_id: uuid.UUID,
        evidence_references: list[str],
    ) -> None:
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        raw_items = metadata.get("runtime_causal_observations")
        if not isinstance(raw_items, list):
            return
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            try:
                observation = RuntimeCausalObservation.model_validate(raw)
                self._evidence_ledger.append_causal_observation(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    producer="tool_runtime_authority",
                    actor=worker_id,
                    observation=observation,
                    causation_id=str(lease_id),
                    correlation_id=str(task.mission_id),
                    evidence_references=evidence_references,
                )
            except (TypeError, ValueError):
                logger.exception("invalid task causal observation for %s", task.id)

    def claim_next_task(self, *, tenant_id: str, worker_id: str) -> ExecutionTask | None:
        message = self._queue.claim_task(tenant_id=tenant_id, worker_id=worker_id)
        if message is None:
            return None

        task = self._tasks.get(message.task_id)
        if task is None or task.tenant_id != tenant_id:
            enqueued_at = message.enqueued_at
            if enqueued_at.tzinfo is None:
                enqueued_at = enqueued_at.replace(tzinfo=UTC)
            payload_age_seconds = max(0.0, (datetime.now(UTC) - enqueued_at).total_seconds())
            if task is None and payload_age_seconds < _QUEUE_PAYLOAD_DB_VISIBILITY_GRACE_SECONDS:
                logger.warning(
                    "claim_task_db_visibility_retry",
                    extra={
                        "task_id": str(message.task_id),
                        "worker_id": worker_id,
                        "payload_age_seconds": payload_age_seconds,
                    },
                )
                released = self._queue.release_lease(
                    tenant_id=tenant_id,
                    task_id=message.task_id,
                    worker_id=worker_id,
                )
                if not released.ok:
                    raise RuntimeError(released.reason or "failed to release queue payload during DB visibility grace")
                return None
            logger.error(
                "claim_task_not_in_db",
                extra={
                    "task_id": str(message.task_id),
                    "worker_id": worker_id,
                    "payload_age_seconds": payload_age_seconds,
                },
            )
            quarantined = self._queue.fail_task(
                tenant_id=tenant_id,
                task_id=message.task_id,
                worker_id=worker_id,
                reason="claimed queue payload has no matching tenant execution task",
            )
            if not quarantined.ok:
                self._queue.release_lease(
                    tenant_id=tenant_id,
                    task_id=message.task_id,
                    worker_id=worker_id,
                )
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=None,
                    category="worker",
                    action="orphan_queue_payload_quarantined"
                    if quarantined.ok
                    else "orphan_queue_payload_quarantine_failed",
                    actor=worker_id,
                    details="Claimed queue payload did not resolve to a tenant-owned execution task.",
                    payload_json={
                        "task_id": str(message.task_id),
                        "payload_mission_id": str(message.mission_id),
                        "payload_age_seconds": payload_age_seconds,
                        "quarantined": quarantined.ok,
                        "reason": quarantined.reason,
                    },
                )
            )
            self._session.commit()
            return None

        if task.status in _TERMINAL_TASK_STATES:
            self._reconcile_claimed_terminal_queue_artifact(
                tenant_id=tenant_id,
                task=task,
                worker_id=worker_id,
            )
            return None

        mission = (
            MissionRepository(self._session).get_for_tenant(mission_id=task.mission_id, tenant_id=tenant_id)
            if task.mission_id is not None
            else None
        )
        if mission is not None and contains_composition_clarification(mission.metadata_json):
            # Stale UI clarification graphs must not execute. Cancel the queued
            # task through the normal task transition and leave an audit trail.
            transition_task(task, ExecutionTaskState.CANCELLED)
            self._session.add(task)
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="worker",
                    action="stale_task_cancelled",
                    actor=worker_id,
                    details="Queued task cancelled because mission intake contains planner clarification text.",
                    payload_json={"task_id": str(task.id)},
                )
            )
            self._maybe_rollup_mission_status(task=task, worker_id=worker_id)
            self._dispatches.cancel(task=task)
            self._session.commit()
            completed = self._queue.complete_task(
                tenant_id=tenant_id,
                task_id=task.id,
                worker_id=worker_id,
            )
            if not completed.ok:
                logger.error(
                    "stale_cancelled_queue_cleanup_failed",
                    extra={"task_id": str(task.id), "worker_id": worker_id, "reason": completed.reason},
                )
            self._dispatches.reconcile_cancelled()
            return None

        savepoint = self._session.begin_nested()
        try:
            self._assert_no_active_lease(tenant_id=tenant_id, task_id=task.id)
            transition_task(task, ExecutionTaskState.CLAIMED)
            lease = self._leases.add(
                WorkerLease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    status=WorkerLeaseState.CLAIMED.value,
                    holder_identity=worker_id,
                    heartbeat_at=datetime.now(UTC),
                )
            )
            task.metadata_json = {**task.metadata_json, "worker_lease_id": str(lease.id)}
            self._session.flush()

            # Ability graph: do not start work until dependency_keys are completed.
            if task.mission_id is not None:
                mission_tasks = self._tasks.list_for_mission(mission_id=task.mission_id)
                pending = pending_dependency_keys(task=task, mission_tasks=mission_tasks)
                if pending:
                    logger.info(
                        "claim_deferred_dependencies",
                        extra={
                            "task_id": str(task.id),
                            "pending_keys": pending,
                            "worker_id": worker_id,
                        },
                    )
                    self._transition_lease_to_released(lease)
                    transition_task(task, ExecutionTaskState.QUEUED)
                    task.metadata_json = {
                        **(task.metadata_json if isinstance(task.metadata_json, dict) else {}),
                        "dependency_deferral": {
                            "pending_keys": pending,
                            "deferred_at": datetime.now(UTC).isoformat(),
                        },
                    }
                    # Drop worker_lease_id so a later claim creates a fresh lease.
                    meta = dict(task.metadata_json)
                    meta.pop("worker_lease_id", None)
                    task.metadata_json = meta
                    self._session.flush()
                    savepoint.commit()
                    self._session.commit()
                    self._queue.release_lease(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        worker_id=worker_id,
                    )
                    return None

            savepoint.commit()
            self._session.commit()
        except Exception as exc:
            logger.error(
                "claim_db_failed_releasing_queue_claim",
                extra={"task_id": str(task.id), "worker_id": worker_id, "error": str(exc)},
            )
            if savepoint.is_active:
                savepoint.rollback()
            else:
                self._session.rollback()
            try:
                self._queue.release_lease(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    worker_id=worker_id,
                )
            except Exception as release_exc:
                logger.critical(
                    "claim_compensation_failed",
                    extra={
                        "task_id": str(task.id),
                        "worker_id": worker_id,
                        "release_error": str(release_exc),
                    },
                )
            raise

        return task

    def heartbeat(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        if lease.status not in {WorkerLeaseState.CLAIMED.value, WorkerLeaseState.ACTIVE.value}:
            raise ValueError("lease is not heartbeat-eligible")

        result = self._queue.heartbeat(tenant_id=tenant_id, task_id=lease.task_id, worker_id=worker_id)
        if not result.ok:
            raise ValueError(result.reason or "heartbeat rejected")

        if lease.status == WorkerLeaseState.CLAIMED.value:
            transition_lease(lease, WorkerLeaseState.ACTIVE)
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def start_execution(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status == ExecutionTaskState.CLAIMED.value:
            if lease.status == WorkerLeaseState.CLAIMED.value:
                transition_lease(lease, WorkerLeaseState.ACTIVE)
            lease.heartbeat_at = datetime.now(UTC)
            transition_task(task, ExecutionTaskState.RUNNING)
            # Bind the evidence obligation to the producing execution, not its
            # later observation. Historical tasks have no inferred version.
            task.metadata_json = {
                **(task.metadata_json if isinstance(task.metadata_json, dict) else {}),
                "runtime_evidence_contract_version": "1",
            }
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    category="mission_information",
                    action="execution_started",
                    actor=worker_id,
                    details="Observed task input representation at execution start",
                    payload_json={
                        "schema_version": 1,
                        "task_id": str(task.id),
                        "lease_id": str(lease.id),
                        "input": describe_information((task.metadata_json or {}).get("input_bindings")),
                        "declared_output": describe_information(
                            (task.metadata_json or {}).get("expected_output_contract")
                        ),
                        "resolved_input": describe_information((task.metadata_json or {}).get("input")),
                        "tool_invocation": describe_information((task.metadata_json or {}).get("tool_invocation")),
                        "grants_execution_authority": False,
                    },
                )
            )
            metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
            invocation = metadata.get("tool_invocation")
            action = invocation.get("action") if isinstance(invocation, dict) else None
            self._evidence_ledger.append_fact(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="execution_task",
                action="started",
                producer="worker_runtime",
                actor=worker_id,
                details=f"Worker started task {task.id} under lease {lease.id}.",
                facts={
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "state": task.status,
                    "task_type": metadata.get("task_type"),
                    "action": action if isinstance(action, str) else None,
                },
                authority_context={"lease_owner": worker_id, "lease_status": lease.status},
                causation_id=str(lease.id),
                correlation_id=str(task.mission_id),
            )
            self._session.flush()
            self._session.commit()
        return task

    def complete(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_output: dict[str, Any] | None = None,
        output_reason: str | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        if isinstance(runtime_metadata, dict):
            # Tool authority runs in the dispatcher session, while completion
            # intentionally uses a fresh lease-owned transaction. Carry only
            # the bounded runtime metadata required for causal evidence and
            # rebound inputs; never replace the authoritative task projection.
            metadata = {
                **metadata,
                **{
                    key: value
                    for key, value in runtime_metadata.items()
                    if key in {"runtime_causal_observations", "input_binding_audit", "tool_invocation"}
                },
            }
            task.metadata_json = metadata
        if metadata.get("cancel_requested"):
            return self._complete_cancel_requested(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
            )
        _validate_declared_output_contract(task, task_output)
        self._evidence_ledger.append_causal_observation(
            tenant_id=tenant_id,
            mission_id=task.mission_id,
            producer="worker_runtime",
            actor=worker_id,
            observation=RuntimeCausalObservation(
                stage="output_validation",
                decision="output_accepted",
                reason_code="declared_contract_validation_passed",
                transformation_id="runtime-output-validation:v1",
                selected_path="accepted",
                field_lineage={"task.output": "declared_output_contract"},
                constraints=("declared_output_contract",),
                safe_metadata={"contract_present": bool(metadata.get("expected_output_contract"))},
            ),
            causation_id=str(lease.id),
            correlation_id=str(task.mission_id),
        )

        transition_task(task, ExecutionTaskState.COMPLETED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        evidence_ids_for_review: list[str] = []
        if task_output is not None:
            task.metadata_json = {**task.metadata_json, **_mirror_task_output_to_metadata(task_output)}
            lineage_record = LineageRecordRepository(self._session).append(
                LineageRecord(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    fleet_id=task.fleet_id,
                    branch_id=task.branch_id,
                    task_id=task.id,
                    worker_lease_id=lease.id,
                    relationship_type="task_output",
                    relationship_reason=output_reason,
                    metadata_json=task_output,
                )
            )
            evidence_repo = EvidenceRepository(self._session)
            for evidence_record in build_tool_action_evidence_records(
                task=task,
                lease=lease,
                task_output=task_output,
                lineage_record=lineage_record,
            ):
                added = evidence_repo.add(evidence_record)
                evidence_ids_for_review.append(str(added.id))
            materialized_artifacts = _materialized_artifact_reference(task, evidence_ids_for_review)
            if materialized_artifacts:
                task.metadata_json = {
                    **task.metadata_json,
                    "materialized_artifacts": materialized_artifacts,
                }
                # The task projection is not the durable evidence contract.
                # Copy the declared artifact identity onto the tenant-scoped
                # evidence row so artifact references survive task projection
                # refreshes and can be reconciled independently.
                for reference in materialized_artifacts:
                    evidence_id = reference.get("evidence_id")
                    if not isinstance(evidence_id, str):
                        continue
                    materialized_evidence = evidence_repo.get_for_tenant(
                        evidence_id=uuid.UUID(evidence_id),
                        tenant_id=task.tenant_id,
                    )
                    if materialized_evidence is None:
                        raise ValueError("materialized artifact evidence is missing for the task tenant")
                    references = list(materialized_evidence.artifact_references or [])
                    if reference not in references:
                        references.append(reference)
                        materialized_evidence.artifact_references = references
                        evidence_repo.update(materialized_evidence)

            # Outcome review bridge for high-risk GTM side-effecting actions (PR pilot coherence)
            # Auto-creates a draft review post-completion for missions launched with high-risk GTM
            # via ability-runtime (where requires_human_review and side_effect_authorization are set).
            # This fulfills the "completion + evidence + outcome review" stage and removes
            # "create_outcome_review" from mission lifecycle missing steps.
            # Creation is internal (no permission gate) and respects OutcomeReview contract
            # (no runtime mutation).
            if self._is_high_risk_gtm_side_effect(task, task_output):
                self._create_draft_outcome_review(
                    task=task,
                    task_output=task_output,
                    evidence_ids=evidence_ids_for_review,
                )

        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="mission_information",
                action="execution_completed",
                actor=worker_id,
                details="Observed task output representation at completion",
                payload_json={
                    "schema_version": 1,
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "output": describe_information(task_output),
                    "evidence_record_ids": evidence_ids_for_review[:100],
                    "evidence_ids_truncated": len(evidence_ids_for_review) > 100,
                    "grants_execution_authority": False,
                },
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completed",
                actor=worker_id,
                details=f"Completed task {task.id}",
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        self._evidence_ledger.append_fact(
            tenant_id=tenant_id,
            mission_id=task.mission_id,
            category="runtime_evidence",
            action="worker_completion_recorded",
            producer="worker_runtime",
            actor=worker_id,
            details=f"Completed task {task.id}",
            facts={"task_id": str(task.id), "lease_id": str(lease.id), "state": task.status},
            authority_context={"lease_owner": worker_id, "lease_status": lease.status},
            causation_id=str(lease.id),
            correlation_id=str(task.mission_id),
            evidence_references=evidence_ids_for_review,
        )
        if task_output is not None:
            for observation in _causal_observation_for_tool_output(task=task, task_output=task_output):
                self._evidence_ledger.append_causal_observation(
                    tenant_id=tenant_id,
                    mission_id=task.mission_id,
                    producer="worker_runtime",
                    actor=worker_id,
                    observation=observation,
                    causation_id=str(lease.id),
                    correlation_id=str(task.mission_id),
                    evidence_references=evidence_ids_for_review,
                )
        self._append_task_causal_observations(
            task=task,
            worker_id=worker_id,
            lease_id=lease.id,
            evidence_references=evidence_ids_for_review,
        )
        self._refresh_deliverable_completion_read_model(task=task)
        self._maybe_rollup_mission_status(task=task, worker_id=worker_id)
        self._session.flush()
        self._session.commit()

        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="terminal_queue_complete_cleanup_failed",
                reason=result.reason or "complete rejected",
            )
        return task

    def _complete_cancel_requested(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
    ) -> ExecutionTask:
        transition_task(task, ExecutionTaskState.CANCELLED)
        self._transition_lease_to_released(lease)
        self._dispatches.cancel(task=task)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_cancelled_after_request",
                actor=worker_id,
                details=f"Cancelled task {task.id} after a stop request; handler output was not committed.",
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        self._session.commit()
        self._finalize_cancelled_queue_cleanup(
            tenant_id=tenant_id,
            task=task,
            lease=lease,
            worker_id=worker_id,
        )
        return task

    def _finalize_cancelled_queue_cleanup(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
    ) -> None:
        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="cancelled_queue_complete_cleanup_failed",
                reason=result.reason or "cancelled task cleanup rejected",
            )
        self._dispatches.reconcile_cancelled()

    def _refresh_deliverable_completion_read_model(self, *, task: ExecutionTask) -> None:
        _refresh_deliverable_completion_read_model_impl(self, task=task)

    def _maybe_rollup_mission_status(self, *, task: ExecutionTask, worker_id: str) -> None:
        _maybe_rollup_mission_status_impl(self, task=task, worker_id=worker_id)

    def cancel_task(self, *, tenant_id: str, task_id: uuid.UUID, actor: str, reason: str) -> ExecutionTask:
        task = self._tasks.get_for_tenant(task_id=task_id, tenant_id=tenant_id)
        if task is None:
            raise ValueError("task not found for tenant")
        if task.status in _TERMINAL_TASK_STATES:
            return task
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        if task.status in {ExecutionTaskState.RUNNING.value, ExecutionTaskState.CLAIMED.value}:
            task.metadata_json = {
                **metadata,
                "cancel_requested": True,
                "cancel_requested_at": datetime.now(UTC).isoformat(),
                "cancel_reason": reason,
            }
            action = "task_cancellation_requested"
        else:
            transition_task(task, ExecutionTaskState.CANCELLED)
            task.metadata_json = {**metadata, "cancel_reason": reason}
            self._dispatches.cancel(task=task)
            action = "task_cancelled"
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action=action,
                actor=actor,
                details=reason,
                payload_json={"task_id": str(task.id), "status": task.status},
            )
        )
        self._maybe_rollup_mission_status(task=task, worker_id=actor)
        self._session.commit()
        if task.status == ExecutionTaskState.CANCELLED.value:
            self._dispatches.reconcile_cancelled()
        return task

    def cancel_mission(self, *, tenant_id: str, mission_id: uuid.UUID, actor: str, reason: str) -> dict[str, Any]:
        mission = MissionRepository(self._session).lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
        if mission is None:
            raise ValueError("mission not found for tenant")
        tasks = self._tasks.list_for_mission_for_tenant(mission_id=mission_id, tenant_id=tenant_id)
        cancelled = requested = 0
        for task in tasks:
            if task.status in _TERMINAL_TASK_STATES:
                continue
            self.cancel_task(tenant_id=tenant_id, task_id=task.id, actor=actor, reason=reason)
            if task.status == ExecutionTaskState.CANCELLED.value:
                cancelled += 1
            else:
                requested += 1
        if mission.status not in {
            MissionState.COMPLETED.value,
            MissionState.FAILED.value,
            MissionState.CANCELLED.value,
            MissionState.ARCHIVED.value,
        }:
            transition_mission(mission, MissionState.CANCELLED)
            mission.metadata_json = {
                **(mission.metadata_json if isinstance(mission.metadata_json, dict) else {}),
                "cancel_reason": reason,
                "cancelled_at": datetime.now(UTC).isoformat(),
            }
            self._audit.append(
                AuditEvent(
                    tenant_id=tenant_id,
                    mission_id=mission_id,
                    category="mission",
                    action="mission_cancelled",
                    actor=actor,
                    details=reason,
                    payload_json={"cancelled_tasks": cancelled, "cancellation_requested_tasks": requested},
                )
            )
        self._session.commit()
        return {
            "mission_id": str(mission_id),
            "status": mission.status,
            "cancelled_tasks": cancelled,
            "cancellation_requested_tasks": requested,
        }

    def block_completion_failure(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        task_type: str,
        side_effect_class: str,
        reason: str,
    ) -> ExecutionTask:
        """Block a task after a side-effecting handler completed but completion persistence failed."""

        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status != ExecutionTaskState.RUNNING.value:
            raise ValueError("task is not running")

        transition_task(task, ExecutionTaskState.BLOCKED)
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="mission_information",
                action="execution_completion_blocked",
                actor=worker_id,
                details="Observed completion persistence failure after side effect",
                payload_json={
                    "schema_version": 1,
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "side_effect_class": side_effect_class,
                    "grants_execution_authority": False,
                },
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_completion_failed_after_side_effect",
                actor=worker_id,
                details=(f"Blocked task {task.id} after completed {task_type} side effect failed completion: {reason}"),
                payload_json={
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "task_type": task_type,
                    "side_effect_class": side_effect_class,
                    "reason": reason,
                    "handler_completed": True,
                    "requeue_allowed": False,
                },
            )
        )
        self._session.flush()
        self._session.commit()

        result = self._queue.complete_task(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="complete_task",
                audit_action="completion_failure_queue_complete_cleanup_failed",
                reason=result.reason or "complete rejected",
            )
        return task

    def fail(
        self,
        *,
        tenant_id: str,
        lease_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> ExecutionTask:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        if task.status not in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            raise ValueError("task is not fail-eligible")

        transition_task(task, ExecutionTaskState.FAILED)
        task.metadata_json = {
            **(task.metadata_json if isinstance(task.metadata_json, dict) else {}),
            "failure": {
                "code": "HANDLER_FAILED",
                "message": reason,
                "retryable": True,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        }
        EvidenceRepository(self._session).add(
            _failure_evidence_record(task=task, lease=lease, worker_id=worker_id, reason=reason)
        )
        self._transition_lease_to_released(lease)
        lease.heartbeat_at = datetime.now(UTC)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="mission_information",
                action="execution_failed",
                actor=worker_id,
                details="Observed terminal execution failure",
                payload_json={
                    "schema_version": 1,
                    "task_id": str(task.id),
                    "lease_id": str(lease.id),
                    "failure_code": "HANDLER_FAILED",
                    "grants_execution_authority": False,
                },
            )
        )
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=task.mission_id,
                category="worker",
                action="task_failed",
                actor=worker_id,
                details=reason,
                payload_json={"task_id": str(task.id), "lease_id": str(lease.id)},
            )
        )
        self._evidence_ledger.append_fact(
            tenant_id=tenant_id,
            mission_id=task.mission_id,
            category="runtime_evidence",
            action="worker_failure_recorded",
            producer="worker_runtime",
            actor=worker_id,
            details=reason,
            facts={"task_id": str(task.id), "lease_id": str(lease.id), "state": task.status, "reason": reason},
            authority_context={"lease_owner": worker_id, "lease_status": lease.status},
            causation_id=str(lease.id),
            correlation_id=str(task.mission_id),
        )
        self._append_task_causal_observations(
            task=task,
            worker_id=worker_id,
            lease_id=lease.id,
            evidence_references=[],
        )
        self._refresh_deliverable_completion_read_model(task=task)
        self._maybe_rollup_mission_status(task=task, worker_id=worker_id)
        self._session.flush()
        self._session.commit()

        result = self._queue.fail_task(
            tenant_id=tenant_id,
            task_id=task.id,
            worker_id=worker_id,
            reason=reason,
        )
        if not result.ok:
            self._record_terminal_queue_cleanup_failure(
                tenant_id=tenant_id,
                task=task,
                lease=lease,
                worker_id=worker_id,
                queue_operation="fail_task",
                audit_action="terminal_queue_fail_cleanup_failed",
                reason=result.reason or "fail rejected",
            )
        return task

    def release(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._get_owned_lease(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        task = self._get_task_for_lease(lease)
        self._assert_current_releasable_claim(tenant_id=tenant_id, lease=lease, task=task)

        self._transition_lease_to_released(lease)
        transition_task(task, ExecutionTaskState.QUEUED)
        result = self._queue.release_lease(
            tenant_id=tenant_id,
            task_id=lease.task_id,
            worker_id=worker_id,
        )
        if not result.ok:
            self._session.rollback()
            raise ValueError(result.reason or "release rejected")
        lease.heartbeat_at = datetime.now(UTC)
        self._session.flush()
        self._session.commit()
        return lease

    def _reconcile_claimed_terminal_queue_artifact(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        worker_id: str,
    ) -> None:
        _reconcile_claimed_terminal_queue_artifact_impl(self, tenant_id=tenant_id, task=task, worker_id=worker_id)

    def _record_terminal_queue_cleanup_failure(
        self,
        *,
        tenant_id: str,
        task: ExecutionTask,
        lease: WorkerLease,
        worker_id: str,
        queue_operation: str,
        audit_action: str,
        reason: str,
    ) -> None:
        _record_terminal_queue_cleanup_failure_impl(
            self,
            tenant_id=tenant_id,
            task=task,
            lease=lease,
            worker_id=worker_id,
            queue_operation=queue_operation,
            audit_action=audit_action,
            reason=reason,
        )

    def _assert_current_releasable_claim(
        self,
        *,
        tenant_id: str,
        lease: WorkerLease,
        task: ExecutionTask,
    ) -> None:
        _assert_current_releasable_claim_impl(self, tenant_id=tenant_id, lease=lease, task=task)

    def _get_owned_lease(self, *, tenant_id: str, lease_id: uuid.UUID, worker_id: str) -> WorkerLease:
        lease = self._leases.get(lease_id)
        if lease is None or lease.tenant_id != tenant_id or lease.holder_identity != worker_id:
            raise ValueError("lease not found for tenant worker")
        return lease

    def _get_task_for_lease(self, lease: WorkerLease) -> ExecutionTask:
        task = self._tasks.get(lease.task_id)
        if task is None:
            raise ValueError("task not found")
        return task

    def _assert_no_active_lease(self, *, tenant_id: str, task_id: uuid.UUID) -> None:
        _assert_no_active_lease_impl(self, tenant_id=tenant_id, task_id=task_id)

    def _transition_lease_to_released(self, lease: WorkerLease) -> None:
        _transition_lease_to_released_impl(self, lease)

    def _gtm_side_effect_was_real(self, task_output: dict[str, Any]) -> bool:
        return _gtm_side_effect_was_real_impl(self, task_output)

    def _is_high_risk_gtm_side_effect(self, task: ExecutionTask, task_output: dict[str, Any] | None) -> bool:
        return _is_high_risk_gtm_side_effect_impl(self, task, task_output)

    def _create_draft_outcome_review(
        self,
        *,
        task: ExecutionTask,
        task_output: dict[str, Any],
        evidence_ids: list[str],
    ) -> None:
        _create_draft_outcome_review_impl(self, task=task, task_output=task_output, evidence_ids=evidence_ids)
