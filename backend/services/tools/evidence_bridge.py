from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EVIDENCE_CONTRACT_SCHEMA_VERSION, EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.services.ontology.evidence_lineage import EvidenceOriginType
from backend.services.tools.schemas import EvidenceItem

_TOOL_INVOKE_HANDLER = "tool.invoke"
_TASK_OUTPUT_RELATIONSHIP = "task_output"
_TOOL_ACTION_EVIDENCE_TYPE = "action_result"
_TOOL_ACTION_EVIDENCE_ALIAS = "action_result_evidence"
_DURABLE_TOOL_ACTION_EVIDENCE_TYPE = "execution_trace"


class CanonicalToolEvidenceError(ValueError):
    """A claimed tool evidence row is not owned by the canonical runtime bridge."""


def build_tool_action_evidence_records(
    *,
    task: ExecutionTask,
    lease: WorkerLease,
    task_output: Mapping[str, Any],
    lineage_record: LineageRecord,
) -> list[EvidenceRecord]:
    """Build durable EvidenceRecord rows from a completed tool.invoke output.

    The bridge is intentionally narrow: it only converts evidence emitted by the
    authoritative ``tool.invoke`` dispatcher result after that result has already
    been attached to task-output lineage. It does not execute tools, mutate
    runtime state, score outcomes, or infer evidence from arbitrary handler
    output.
    """

    if task_output.get("handler") != _TOOL_INVOKE_HANDLER:
        return []
    if task_output.get("status") != "completed":
        return []
    if lineage_record.relationship_type != _TASK_OUTPUT_RELATIONSHIP:
        raise ValueError("tool action evidence bridge requires task_output lineage")

    raw_evidence = task_output.get("evidence")
    if raw_evidence is None:
        raise ValueError("tool.invoke output must include evidence")
    if not isinstance(raw_evidence, list):
        raise ValueError("tool.invoke evidence output must be a list")
    if not raw_evidence:
        raise ValueError("tool.invoke evidence output must be non-empty")

    records: list[EvidenceRecord] = []
    for index, raw_item in enumerate(raw_evidence):
        if not isinstance(raw_item, Mapping):
            raise ValueError("tool.invoke evidence items must be objects")
        evidence_item = EvidenceItem.model_validate(dict(raw_item))
        _validate_evidence_scope(task=task, evidence_item=evidence_item)
        records.append(
            _build_tool_action_evidence_record(
                task=task,
                lease=lease,
                task_output=task_output,
                lineage_record=lineage_record,
                evidence_index=index,
                evidence_item=evidence_item,
                evidence_record_id=uuid.uuid4(),
            )
        )
    return records


def require_canonical_tool_action_evidence(
    *,
    session: Session,
    record: EvidenceRecord,
    expected_action: str,
    expected_role: str | None,
) -> EvidenceItem:
    """Prove a durable row is the unique runtime projection of task-output lineage.

    Public Evidence API callers can author declarative JSON, so JSON labels alone
    never establish runtime ownership. This validator binds the row to relational
    task/lease/lineage authorities and reconstructs the exact EvidenceBridge output.
    """

    if record.execution_task_id is None:
        raise CanonicalToolEvidenceError("canonical tool evidence requires execution-task provenance")
    reference = record.materialization_reference
    if not isinstance(reference, Mapping):
        raise CanonicalToolEvidenceError("canonical tool evidence requires a materialization reference")
    lease_id = _required_reference_uuid(reference, "worker_lease_id")
    lineage_id = _required_reference_uuid(reference, "lineage_record_id")
    evidence_index = reference.get("evidence_index")
    if isinstance(evidence_index, bool) or not isinstance(evidence_index, int) or evidence_index < 0:
        raise CanonicalToolEvidenceError("canonical tool evidence requires a valid evidence index")

    task = session.get(ExecutionTask, record.execution_task_id)
    lease = session.get(WorkerLease, lease_id)
    lineage = session.get(LineageRecord, lineage_id)
    if task is None or lease is None or lineage is None:
        raise CanonicalToolEvidenceError("canonical tool evidence runtime provenance is inaccessible")
    if task.status != ExecutionTaskState.COMPLETED.value:
        raise CanonicalToolEvidenceError("canonical tool evidence task is not completed")
    if lease.status != WorkerLeaseState.RELEASED.value:
        raise CanonicalToolEvidenceError("canonical tool evidence lease is not released")
    if (
        task.tenant_id != record.tenant_id
        or task.mission_id != record.mission_id
        or lease.tenant_id != record.tenant_id
        or lease.task_id != task.id
        or lineage.tenant_id != record.tenant_id
        or lineage.mission_id != record.mission_id
        or lineage.task_id != task.id
        or lineage.worker_lease_id != lease.id
        or lineage.relationship_type != _TASK_OUTPUT_RELATIONSHIP
    ):
        raise CanonicalToolEvidenceError("canonical tool evidence runtime scope disagrees")

    invocation = task.metadata_json.get("tool_invocation")
    task_output = lineage.metadata_json
    if not isinstance(invocation, Mapping) or invocation.get("action") != expected_action:
        raise CanonicalToolEvidenceError("canonical tool evidence task does not own the expected action")
    if task.metadata_json.get("handler_result") != task_output:
        raise CanonicalToolEvidenceError("canonical tool evidence task output and lineage disagree")
    if (
        task_output.get("handler") != _TOOL_INVOKE_HANDLER
        or task_output.get("status") != "completed"
        or task_output.get("action") != expected_action
    ):
        raise CanonicalToolEvidenceError("canonical tool evidence lineage does not prove the expected action")

    raw_evidence = task_output.get("evidence")
    if not isinstance(raw_evidence, list) or evidence_index >= len(raw_evidence):
        raise CanonicalToolEvidenceError("canonical tool evidence index is outside task output")
    raw_item = raw_evidence[evidence_index]
    if not isinstance(raw_item, Mapping):
        raise CanonicalToolEvidenceError("canonical tool evidence item is malformed")
    evidence_item = EvidenceItem.model_validate(dict(raw_item))
    if evidence_item.action_name != expected_action or (
        expected_role is not None and evidence_item.provenance.get("evidence_role") != expected_role
    ):
        raise CanonicalToolEvidenceError("canonical tool evidence semantic owner disagrees")
    _validate_evidence_scope(task=task, evidence_item=evidence_item)
    expected = _build_tool_action_evidence_record(
        task=task,
        lease=lease,
        task_output=task_output,
        lineage_record=lineage,
        evidence_index=evidence_index,
        evidence_item=evidence_item,
        evidence_record_id=record.id,
    )
    _require_exact_bridge_projection(record=record, expected=expected)

    task_records = session.scalars(select(EvidenceRecord).where(EvidenceRecord.execution_task_id == task.id)).all()
    same_projection = [
        item
        for item in task_records
        if isinstance(item.materialization_reference, Mapping)
        and item.materialization_reference.get("lineage_record_id") == str(lineage.id)
        and item.materialization_reference.get("evidence_index") == evidence_index
    ]
    if len(same_projection) != 1 or same_projection[0].id != record.id:
        raise CanonicalToolEvidenceError("canonical tool evidence projection is not unique")
    return evidence_item


def require_canonical_source_observation_evidence(
    *,
    session: Session,
    record: EvidenceRecord,
) -> EvidenceItem:
    """Prove source-observation semantics were emitted by the runtime action owner."""

    reference = record.materialization_reference
    if not isinstance(reference, Mapping):
        raise CanonicalToolEvidenceError("source observation requires canonical runtime provenance")
    expected_action = reference.get("action")
    if not isinstance(expected_action, str) or not expected_action.strip():
        raise CanonicalToolEvidenceError("source observation requires a canonical action owner")
    evidence_item = require_canonical_tool_action_evidence(
        session=session,
        record=record,
        expected_action=expected_action,
        expected_role=None,
    )
    if evidence_item.lineage is None or evidence_item.lineage.origin_type != EvidenceOriginType.SOURCE_OBSERVATION:
        raise CanonicalToolEvidenceError("runtime action did not establish source-observation authority")
    if evidence_item.side_effect_class.has_side_effect:
        raise CanonicalToolEvidenceError("source observation must be produced by a non-mutating authority")
    return evidence_item


def _build_tool_action_evidence_record(
    *,
    task: ExecutionTask,
    lease: WorkerLease,
    task_output: Mapping[str, Any],
    lineage_record: LineageRecord,
    evidence_index: int,
    evidence_item: EvidenceItem,
    evidence_record_id: uuid.UUID,
) -> EvidenceRecord:
    durable_lineage = (
        evidence_item.lineage.model_copy(update={"artifact_evidence_id": str(evidence_record_id)})
        if evidence_item.lineage is not None
        else None
    )
    return EvidenceRecord(
        id=evidence_record_id,
        tenant_id=task.tenant_id,
        mission_id=task.mission_id,
        task_graph_node_key=_optional_string(task.metadata_json.get("task_graph_node_key")),
        materialization_reference=_build_materialization_reference(
            task=task,
            lease=lease,
            task_output=task_output,
            lineage_record=lineage_record,
            evidence_index=evidence_index,
        ),
        execution_task_id=task.id,
        capability_id=_reference_uuid(task.metadata_json.get("capability_reference"), "capability_id"),
        capability_adapter_id=_reference_uuid(task.metadata_json.get("adapter_reference"), "adapter_id"),
        evidence_type=_durable_evidence_type(evidence_item.evidence_type),
        evidence_source=evidence_item.evidence_source,
        summary=evidence_item.summary,
        structured_payload=evidence_item.structured_payload,
        artifact_references=[
            {
                "artifact_type": "lineage_record",
                "relationship_type": lineage_record.relationship_type,
                "relationship_reason": lineage_record.relationship_reason,
                "lineage_record_id": str(lineage_record.id),
            }
        ],
        provenance_metadata={
            **evidence_item.provenance,
            **({"evidence_lineage": durable_lineage.model_dump(mode="json")} if durable_lineage is not None else {}),
            "runtime_path": "TaskDispatcher -> WorkerRuntimeService.complete -> EvidenceRecord",
            "action_name": evidence_item.action_name,
            "tool_provider": evidence_item.tool_provider,
            "tool_evidence_type": evidence_item.evidence_type,
            "worker_lease_id": str(lease.id),
            "records_inspected": evidence_item.records_inspected,
            "records_changed": evidence_item.records_changed,
            "limitations": evidence_item.limitations,
        },
        trust_signal={
            "confidence": evidence_item.confidence,
            "side_effect_class": evidence_item.side_effect_class.value,
            "collection_status": evidence_item.collection_status,
        },
        confidence=evidence_item.confidence,
        collection_status=evidence_item.collection_status,
        schema_version=EVIDENCE_CONTRACT_SCHEMA_VERSION,
    )


def _require_exact_bridge_projection(*, record: EvidenceRecord, expected: EvidenceRecord) -> None:
    fields = (
        "tenant_id",
        "mission_id",
        "task_graph_node_key",
        "materialization_reference",
        "execution_task_id",
        "capability_id",
        "capability_adapter_id",
        "evidence_type",
        "evidence_source",
        "summary",
        "structured_payload",
        "artifact_references",
        "provenance_metadata",
        "trust_signal",
        "confidence",
        "collection_status",
        "schema_version",
    )
    if any(getattr(record, field) != getattr(expected, field) for field in fields):
        raise CanonicalToolEvidenceError("durable evidence is not the canonical runtime bridge projection")


def _durable_evidence_type(evidence_type: str) -> str:
    if evidence_type in {_TOOL_ACTION_EVIDENCE_TYPE, _TOOL_ACTION_EVIDENCE_ALIAS}:
        return _DURABLE_TOOL_ACTION_EVIDENCE_TYPE
    return evidence_type


def _validate_evidence_scope(*, task: ExecutionTask, evidence_item: EvidenceItem) -> None:
    if evidence_item.tenant_id != task.tenant_id:
        raise ValueError("tool.invoke evidence tenant_id must match task tenant_id")
    if evidence_item.task_id != str(task.id):
        raise ValueError("tool.invoke evidence task_id must match execution task id")
    if evidence_item.mission_id is not None and evidence_item.mission_id != str(task.mission_id):
        raise ValueError("tool.invoke evidence mission_id must match execution task mission_id")


def _build_materialization_reference(
    *,
    task: ExecutionTask,
    lease: WorkerLease,
    task_output: Mapping[str, Any],
    lineage_record: LineageRecord,
    evidence_index: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "tool.invoke.task_output",
        "handler": task_output.get("handler"),
        "action": task_output.get("action"),
        "requested_action": task_output.get("requested_action"),
        "provider": task_output.get("provider"),
        "side_effect_class": task_output.get("side_effect_class"),
        "execution_task_id": str(task.id),
        "worker_lease_id": str(lease.id),
        "lineage_record_id": str(lineage_record.id),
        "evidence_index": evidence_index,
    }


def _optional_string(value: object) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _reference_uuid(reference: object, key: str) -> uuid.UUID | None:
    if not isinstance(reference, Mapping):
        return None
    raw_value = reference.get(key)
    if not raw_value:
        return None
    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return None


def _required_reference_uuid(reference: Mapping[str, Any], key: str) -> uuid.UUID:
    value = _reference_uuid(reference, key)
    if value is None:
        raise CanonicalToolEvidenceError(f"canonical tool evidence requires {key}")
    return value
