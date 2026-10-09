from __future__ import annotations

from typing import Any

from backend.api.routes.ability_runtime_contracts import AbilityTaskCreate
from backend.domain.audit_event import AuditEvent
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.evidence import EvidenceRecord
from backend.domain.lineage_record import LineageRecord

def _build_task_metadata(
    *,
    action_name: str,
    input_payload: dict[str, Any],
    capability: Capability | None,
    adapter: CapabilityAdapter | None,
    request_body: AbilityTaskCreate,
    autonomy_acknowledgment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "task_type": "tool.invoke",
        "launched_by": "ability-runtime",
        "tool_invocation": {
            "schema_version": 1,
            "action": action_name,
            "input": input_payload,
        },
    }

    if request_body.idempotency_key:
        metadata["tool_invocation"]["idempotency_key"] = request_body.idempotency_key

    if capability is not None:
        metadata["capability_reference"] = {"capability_id": str(capability.id)}
    if adapter is not None:
        metadata["adapter_reference"] = {"adapter_id": str(adapter.id)}

    if autonomy_acknowledgment is not None:
        execution_constraints: dict[str, Any] = {}
        execution_constraints["autonomy_acknowledgment"] = autonomy_acknowledgment
        metadata["execution_constraints"] = execution_constraints

    if request_body.credential_reference is not None:
        metadata["credential_reference"] = request_body.credential_reference.model_dump(mode="json")

    return metadata

def _lineage_to_read(record: LineageRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id) if record.mission_id else None,
        "task_id": str(record.task_id) if record.task_id else None,
        "fleet_id": str(record.fleet_id) if record.fleet_id else None,
        "branch_id": str(record.branch_id) if record.branch_id else None,
        "worker_lease_id": str(record.worker_lease_id) if record.worker_lease_id else None,
        "relationship_type": record.relationship_type,
        "relationship_reason": record.relationship_reason,
        "metadata_json": record.metadata_json,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }

def _evidence_to_read(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id),
        "execution_task_id": str(record.execution_task_id) if record.execution_task_id else None,
        "capability_id": str(record.capability_id) if record.capability_id else None,
        "capability_adapter_id": str(record.capability_adapter_id) if record.capability_adapter_id else None,
        "evidence_type": record.evidence_type,
        "evidence_source": record.evidence_source,
        "summary": record.summary,
        "structured_payload": record.structured_payload,
        "artifact_references": record.artifact_references,
        "provenance_metadata": record.provenance_metadata,
        "trust_signal": record.trust_signal,
        "confidence": record.confidence,
        "collection_status": record.collection_status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }

def _audit_to_read(record: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id) if record.mission_id else None,
        "category": record.category,
        "action": record.action,
        "actor": record.actor,
        "details": record.details,
        "payload_json": record.payload_json,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }

