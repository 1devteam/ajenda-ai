from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from backend.domain.evidence import EVIDENCE_CONTRACT_SCHEMA_VERSION, EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.services.tools.schemas import EvidenceItem

_TOOL_INVOKE_HANDLER = "tool.invoke"
_TASK_OUTPUT_RELATIONSHIP = "task_output"
_TOOL_ACTION_EVIDENCE_TYPE = "action_result"
_DURABLE_TOOL_ACTION_EVIDENCE_TYPE = "execution_trace"


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
            EvidenceRecord(
                tenant_id=task.tenant_id,
                mission_id=task.mission_id,
                task_graph_node_key=_optional_string(task.metadata_json.get("task_graph_node_key")),
                materialization_reference=_build_materialization_reference(
                    task=task,
                    lease=lease,
                    task_output=task_output,
                    lineage_record=lineage_record,
                    evidence_index=index,
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
        )
    return records


def _durable_evidence_type(evidence_type: str) -> str:
    if evidence_type == _TOOL_ACTION_EVIDENCE_TYPE:
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
    return uuid.UUID(str(raw_value))
