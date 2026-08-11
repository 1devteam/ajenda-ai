from __future__ import annotations

import uuid

import pytest

from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records
from backend.services.tools.schemas import SideEffectClass


def _task(*, tenant_id: str | None = None, task_id: uuid.UUID | None = None) -> ExecutionTask:
    return ExecutionTask(
        id=task_id or uuid.uuid4(),
        tenant_id=tenant_id or str(uuid.uuid4()),
        mission_id=uuid.uuid4(),
        title="tool task",
        description="tool task",
        status="running",
        metadata_json={"task_type": "tool.invoke", "task_graph_node_key": "node-1"},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _lease(*, task: ExecutionTask) -> WorkerLease:
    return WorkerLease(
        id=uuid.uuid4(),
        tenant_id=task.tenant_id,
        task_id=task.id,
        status="active",
        holder_identity="worker",
    )


def _lineage(*, task: ExecutionTask, lease: WorkerLease) -> LineageRecord:
    return LineageRecord(
        id=uuid.uuid4(),
        tenant_id=task.tenant_id,
        mission_id=task.mission_id,
        task_id=task.id,
        worker_lease_id=lease.id,
        relationship_type="task_output",
        relationship_reason="tool action completed",
        metadata_json={},
    )


def _tool_output(*, task: ExecutionTask, lease: WorkerLease) -> dict[str, object]:
    return {
        "handler": "tool.invoke",
        "status": "completed",
        "schema_version": 1,
        "action": "record.search",
        "requested_action": "record.search",
        "provider": "local_records",
        "side_effect_class": SideEffectClass.NONE.value,
        "output": {"count": 1},
        "evidence": [
            {
                "evidence_type": "action_result",
                "evidence_source": "tool.invoke.record.search",
                "action_name": "record.search",
                "tool_provider": "local_records",
                "tenant_id": task.tenant_id,
                "task_id": str(task.id),
                "mission_id": str(task.mission_id),
                "summary": "Found 1 account record.",
                "structured_payload": {"count": 1},
                "records_inspected": ["acct-1"],
                "records_changed": [],
                "confidence": 1.0,
                "limitations": ["local proof provider"],
                "provenance": {"provider": "LocalRecordProvider"},
                "lineage": {
                    "origin_type": "source_observation",
                    "source_identity": {"source_system": "local_records", "source_record_id": "acct-1"},
                    "root_evidence_ids": ["record:acct-1"],
                    "resolution": "known",
                },
                "side_effect_class": SideEffectClass.NONE.value,
                "collection_status": "collected",
            }
        ],
        "records_inspected": ["acct-1"],
        "records_changed": [],
        "summary": "Found 1 account record.",
        "confidence": 1.0,
        "limitations": [],
        "runtime_context": {"worker_id": "worker", "lease_id": str(lease.id)},
    }


def test_build_tool_action_evidence_records_maps_evidence_to_durable_contract() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=_tool_output(task=task, lease=lease),
        lineage_record=lineage,
    )

    assert len(records) == 1
    record = records[0]
    assert record.tenant_id == task.tenant_id
    assert record.mission_id == task.mission_id
    assert record.execution_task_id == task.id
    assert record.task_graph_node_key == "node-1"
    assert record.evidence_type == "execution_trace"
    assert record.evidence_source == "tool.invoke.record.search"
    assert record.structured_payload == {"count": 1}
    assert record.artifact_references == [
        {
            "artifact_type": "lineage_record",
            "relationship_type": "task_output",
            "relationship_reason": "tool action completed",
            "lineage_record_id": str(lineage.id),
        }
    ]
    assert (
        record.provenance_metadata["runtime_path"]
        == "TaskDispatcher -> WorkerRuntimeService.complete -> EvidenceRecord"
    )
    assert record.provenance_metadata["tool_evidence_type"] == "action_result"
    assert record.provenance_metadata["records_inspected"] == ["acct-1"]
    assert record.provenance_metadata["evidence_lineage"] == {
        "schema_version": 1,
        "origin_type": "source_observation",
        "source_identity": {"source_system": "local_records", "source_record_id": "acct-1"},
        "root_evidence_ids": ["record:acct-1"],
        "parent_evidence_ids": [],
        "ancestor_evidence_ids": [],
        "resolution": "known",
    }
    assert record.trust_signal == {
        "confidence": 1.0,
        "side_effect_class": SideEffectClass.NONE.value,
        "collection_status": "collected",
    }
    assert record.collection_status == "collected"


def test_build_tool_action_evidence_records_maps_action_result_evidence_alias() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)
    output = _tool_output(task=task, lease=lease)
    output["evidence"][0]["evidence_type"] = "action_result_evidence"  # type: ignore[index]

    records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=output,
        lineage_record=lineage,
    )

    assert len(records) == 1
    assert records[0].evidence_type == "execution_trace"
    assert records[0].provenance_metadata["tool_evidence_type"] == "action_result_evidence"


def test_build_tool_action_evidence_records_ignores_non_tool_outputs() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    assert (
        build_tool_action_evidence_records(
            task=task,
            lease=lease,
            task_output={"handler": "echo", "status": "completed"},
            lineage_record=lineage,
        )
        == []
    )


def test_build_tool_action_evidence_records_requires_tool_evidence() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    with pytest.raises(ValueError, match="must include evidence"):
        build_tool_action_evidence_records(
            task=task,
            lease=lease,
            task_output={"handler": "tool.invoke", "status": "completed"},
            lineage_record=lineage,
        )

    with pytest.raises(ValueError, match="must be non-empty"):
        build_tool_action_evidence_records(
            task=task,
            lease=lease,
            task_output={"handler": "tool.invoke", "status": "completed", "evidence": []},
            lineage_record=lineage,
        )


def test_build_tool_action_evidence_records_fails_closed_on_scope_mismatch() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)
    output = _tool_output(task=task, lease=lease)
    output["evidence"][0]["tenant_id"] = str(uuid.uuid4())  # type: ignore[index]

    with pytest.raises(ValueError, match="tenant_id must match"):
        build_tool_action_evidence_records(
            task=task,
            lease=lease,
            task_output=output,
            lineage_record=lineage,
        )


def test_build_tool_action_evidence_records_requires_task_output_lineage() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)
    lineage.relationship_type = "other"

    with pytest.raises(ValueError, match="task_output lineage"):
        build_tool_action_evidence_records(
            task=task,
            lease=lease,
            task_output=_tool_output(task=task, lease=lease),
            lineage_record=lineage,
        )


def test_build_tool_action_evidence_records_ignores_incomplete_tool_output() -> None:
    task = _task()
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)
    output = _tool_output(task=task, lease=lease)
    output["status"] = "failed"

    assert build_tool_action_evidence_records(task=task, lease=lease, task_output=output, lineage_record=lineage) == []


def test_build_tool_action_evidence_records_handles_malformed_optional_task_graph_node_key_safely() -> None:
    task = _task()
    task.metadata_json["task_graph_node_key"] = {"unexpected": "object"}
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=_tool_output(task=task, lease=lease),
        lineage_record=lineage,
    )

    assert len(records) == 1
    assert records[0].task_graph_node_key is None


def test_build_tool_action_evidence_records_handles_malformed_optional_capability_reference_safely() -> None:
    task = _task()
    task.metadata_json["capability_reference"] = {"capability_id": "not-a-uuid"}
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=_tool_output(task=task, lease=lease),
        lineage_record=lineage,
    )

    assert len(records) == 1
    assert records[0].capability_id is None


def test_build_tool_action_evidence_records_handles_malformed_optional_adapter_reference_safely() -> None:
    task = _task()
    task.metadata_json["adapter_reference"] = {"adapter_id": "not-a-uuid"}
    lease = _lease(task=task)
    lineage = _lineage(task=task, lease=lease)

    records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=_tool_output(task=task, lease=lease),
        lineage_record=lineage,
    )

    assert len(records) == 1
    assert records[0].capability_adapter_id is None


def test_evidence_api_create_does_not_call_runtime_bridge() -> None:
    from pathlib import Path

    route_source = Path("backend/api/routes/evidence.py").read_text()

    assert "build_tool_action_evidence_records" not in route_source
    assert "evidence_bridge" not in route_source


def test_runtime_bridge_does_not_call_evidence_api_route() -> None:
    from pathlib import Path

    bridge_source = Path("backend/services/tools/evidence_bridge.py").read_text()

    assert "backend.api.routes.evidence" not in bridge_source
