from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from backend.services.mission_runtime_evidence_projection import (
    build_mission_runtime_evidence_projection,
)


def _task(*, mission_id, tenant_id, status, metadata=None):
    return SimpleNamespace(
        id=uuid4(), mission_id=mission_id, tenant_id=tenant_id, status=status, metadata_json=metadata or {}
    )


def test_projection_exposes_first_missing_worker_edge_without_claiming_success() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="running",
        metadata={"task_type": "web.research"},
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert projection.read_only is True
    assert projection.grants_execution_authority is False
    assert projection.first_divergence == "task:worker_lease"
    assert f"task:{task.id}:state_running_without_worker_lease" in projection.contradictions
    assert any(node.id == f"queue:{task.id}" and node.kind == "queue" for node in projection.nodes)


def test_projection_flags_completed_task_without_evidence() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={"task_type": "web.research"},
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert f"task:{task.id}:evidence" in projection.missing_evidence
    assert f"task:{task.id}:completed_without_evidence" in projection.contradictions


def test_projection_names_declared_artifact_when_completed_output_is_missing() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "expected_output_contract": {"artifact": "observed_contacts"},
            "output": {"verified_prospect_candidates": []},
        },
    )
    lease = SimpleNamespace(
        id=uuid4(),
        task_id=task.id,
        tenant_id=tenant_id,
        status="released",
        holder_identity="worker-test",
    )
    evidence = SimpleNamespace(
        id=uuid4(),
        execution_task_id=task.id,
        tenant_id=tenant_id,
        collection_status="collected",
        evidence_type="execution_trace",
        evidence_source="test",
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[lease],
        lineage=[],
        evidence=[evidence],
    )

    assert projection.first_divergence == "task:artifact"
    assert f"task:{task.id}:artifact:observed_contacts" in projection.missing_evidence
    assert f"task:{task.id}:completed_without_artifact:observed_contacts" in projection.contradictions


def test_projection_accepts_declared_intermediate_output_even_when_read_model_filters_it() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "expected_output_contract": {
                "artifact": "prospect_candidates",
                "materialization_role": "intermediate",
            },
            "handler_result": {
                "output": {"prospect_candidates": [{"company": "Directory result", "source": "public_search"}]}
            },
        },
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert f"task:{task.id}:artifact:prospect_candidates" not in projection.missing_evidence
    assert f"task:{task.id}:completed_without_artifact:prospect_candidates" not in projection.contradictions


def test_projection_exposes_available_selected_and_observed_task_flow() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "node_key": "research",
            "task_type": "tool.invoke",
            "input_bindings": [{"from_step": "compose", "output_path": "prospect_candidates"}],
            "expected_output_contract": {"artifact": "verified_prospect_candidates"},
            "handler_result": {"output": {"verified_prospect_candidates": [{"company": "Acme HVAC"}]}},
        },
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "mission_task_graph": {
                "nodes": [{"key": "research", "output_contract": {"artifact": "verified_prospect_candidates"}}],
                "edges": [],
            },
            "runtime_admission": {"selected_nodes": [{"node_key": "research"}]},
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert projection.available_nodes[0]["key"] == "research"
    assert projection.available_nodes[0]["selected_for_runtime"] is True
    assert projection.selected_nodes == [{"node_key": "research"}]
    flow = projection.task_flows[0]
    assert flow["node_key"] == "research"
    assert flow["input_bindings"][0]["from_step"] == "compose"
    assert flow["observed_output_keys"] == ["verified_prospect_candidates"]
