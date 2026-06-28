"""Full mission bridge → materialize → queue admit → worker dispatch for retrieval.hybrid_search."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
)
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID
from backend.repositories.ephemeral_memory_chunk_repository import EphemeralMemoryChunkRepository
from backend.services.ajenda_demo_fixtures import seed_ajenda_live_demo
from backend.services.mission_bridge_runtime_authority import provision_bridge_runtime_authority
from backend.services.mission_runtime_queue_admission_service import MissionRuntimeQueueAdmissionService
from backend.services.mission_runtime_task_materialization_service import MissionRuntimeTaskMaterializationService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration

_NODE_KEY = "hybrid-retrieval"
_GRAPH_FINGERPRINT = "sha256:retrieval-mission-graph"


def _retrieval_task_graph(*, mission_id: uuid.UUID, capability_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "graph_status": "approved",
        "graph_version": 1,
        "graph_fingerprint": _GRAPH_FINGERPRINT,
        "nodes": [
            {
                "key": _NODE_KEY,
                "name": "Hybrid memory retrieval",
                "intended_task_type": "tool.invoke",
                "capability_references": [
                    {
                        "capability_id": capability_id,
                        "name": "bridge_retrieval_hybrid_search",
                        "version": "1.0.0",
                        "purpose": "Search governed internal and ephemeral mission memory.",
                    }
                ],
                "input_contract": {
                    "tool_invocation": {
                        "schema_version": 1,
                        "action": "retrieval.hybrid_search",
                        "input": {"query": "Ajenda AI", "limit": 5},
                    }
                },
                "expected_output_contract": {"artifact": "memory_hits"},
                "execution_constraints": {"read_only": True},
                "operator_notes": "Real mission retrieval task proof.",
            }
        ],
        "edges": [],
        "operator_notes": "Single-node retrieval mission graph.",
    }


def _graph_reference(task_graph: dict[str, object]) -> dict[str, object]:
    return {
        "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
        "schema_version": task_graph["schema_version"],
        "graph_status": task_graph["graph_status"],
        "graph_version": task_graph["graph_version"],
        "graph_fingerprint": task_graph["graph_fingerprint"],
        "node_count": len(task_graph["nodes"]),
        "edge_count": len(task_graph["edges"]),
    }


def test_mission_materializes_queues_and_executes_retrieval_hybrid_task(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    tenant_id = uuid.uuid4()
    tenant_id_str = str(tenant_id)
    worker_id = "worker-mission-retrieval"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup = session_factory()
    try:
        setup.add(
            Tenant(id=tenant_id, name="Mission Retrieval Tenant", slug=f"mission-retrieval-{tenant_id.hex[:8]}", plan="free")
        )
        mission = Mission(
            tenant_id=tenant_id_str,
            objective="Recover governed outreach memory before drafting follow-up.",
            status="running",
            metadata_json={MISSION_INTAKE_METADATA_KEY: {"schema_version": 1}},
        )
        setup.add(mission)
        setup.flush()
        mission_id = mission.id

        provisional_graph = _retrieval_task_graph(mission_id=mission_id, capability_id=str(uuid.uuid4()))
        mission.metadata_json = {
            **mission.metadata_json,
            MISSION_TASK_GRAPH_METADATA_KEY: provisional_graph,
        }
        flag_modified(mission, "metadata_json")
        setup.flush()

        bridge = provision_bridge_runtime_authority(
            db=setup,
            mission_id=mission_id,
            tenant_id=tenant_id,
            admitted_by="integration-test",
        )
        node_authority = bridge["node_authorities"][0]
        capability_id = node_authority["capability_id"]
        adapter_id = node_authority["adapter_id"]

        task_graph = _retrieval_task_graph(mission_id=mission_id, capability_id=capability_id)
        graph_ref = _graph_reference(task_graph)
        mission.metadata_json = {
            **mission.metadata_json,
            MISSION_TASK_GRAPH_METADATA_KEY: task_graph,
            MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: {
            "schema_version": 1,
            "mission_id": str(mission_id),
            "materialization_status": "validated",
            "materialization_version": 1,
            "capability_selection_provenance": [
                {
                    "node_key": _NODE_KEY,
                    "capability_name": "bridge_retrieval_hybrid_search",
                    "selection_reason": "Mission bridge authority for retrieval.hybrid_search.",
                }
            ],
            "graph_reference": graph_ref,
            },
        }
        materialization_ref = {
            "metadata_key": MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
            "schema_version": 1,
            "materialization_status": "validated",
            "materialization_version": 1,
            "graph_reference": graph_ref,
        }
        now = datetime.now(UTC).isoformat()
        mission.metadata_json = {
            **mission.metadata_json,
            MISSION_RUNTIME_ADMISSION_METADATA_KEY: {
            "schema_version": 1,
            "mission_id": str(mission_id),
            "admission_status": "admitted",
            "admission_version": 1,
            "admitted_by": "integration-test",
            "admitted_at": now,
            "updated_at": now,
            "graph_reference": graph_ref,
            "materialization_reference": materialization_ref,
            "selected_nodes": [
                {
                    "node_key": _NODE_KEY,
                    "runtime_task_type": "tool.invoke",
                    "capability_id": capability_id,
                    "adapter_id": adapter_id,
                    "graph_node_reference": {"key": _NODE_KEY, "name": "Hybrid memory retrieval"},
                    "materialization_selection_reference": {
                        "node_key": _NODE_KEY,
                        "capability_name": "bridge_retrieval_hybrid_search",
                        "selection_reason": "Mission bridge authority for retrieval.hybrid_search.",
                    },
                    "operator_notes": "Execute governed hybrid retrieval.",
                }
            ],
            "validation_result": {
                "validation_status": "valid",
                "summary": "Ready for runtime task materialization.",
                "checks": [],
                "gaps": [],
            },
            "execution_task_records": [],
            "runtime_authority": {
                "creates_execution_tasks": False,
                "enqueues_work": False,
                "dispatches_workers": False,
                "requires_explicit_queue_admission_for_execution": True,
            },
            },
        }
        flag_modified(mission, "metadata_json")

        activate_tenant_session(setup, tenant_id_str)
        seed_ajenda_live_demo(session=setup, tenant_id=tenant_id_str)
        memory_repo = EphemeralMemoryChunkRepository(setup)
        memory_repo.upsert_chunk(
            tenant_id=tenant_id_str,
            content="Approved outreach playbook for Austin roofing leads",
            mission_id=str(mission_id),
            chunk_id="mission-retrieval-chunk",
        )
        setup.commit()
    finally:
        setup.close()

    materialize_session = session_factory()
    try:
        materialized = MissionRuntimeTaskMaterializationService(materialize_session).materialize(
            mission_id=mission_id,
            tenant_id=tenant_id,
        )
        assert materialized.materialization_status == "materialized"
        assert len(materialized.created_execution_task_ids) == 1
        task_id = materialized.created_execution_task_ids[0]
        materialize_session.commit()
    finally:
        materialize_session.close()

    admit_session = session_factory()
    try:
        admitted = MissionRuntimeQueueAdmissionService(admit_session, queue_adapter).admit(
            mission_id=mission_id,
            tenant_id=tenant_id,
        )
        assert admitted["admission_status"] == "admitted"
        assert str(task_id) in admitted["queued_task_ids"]
        admit_session.commit()
    finally:
        admit_session.close()

    claim_session = session_factory()
    try:
        activate_tenant_session(claim_session, tenant_id_str)
        runtime = WorkerRuntimeService(claim_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id_str, worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id_str, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id_str, lease_id=lease_id, worker_id=worker_id)
        claim_session.commit()
    finally:
        claim_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        vector_session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id_str,
    ).execute(task_id=task_id, lease_id=lease_id)

    verify = session_factory()
    try:
        final_task = verify.get(ExecutionTask, task_id)
        final_lease = verify.get(WorkerLease, lease_id)
        lineage = verify.scalars(
            select(LineageRecord).where(
                LineageRecord.tenant_id == tenant_id_str,
                LineageRecord.task_id == task_id,
                LineageRecord.relationship_type == "task_output",
            )
        ).all()
        evidence_records = verify.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id_str,
                EvidenceRecord.execution_task_id == task_id,
            )
        ).all()

        assert final_task is not None
        assert final_task.mission_id == mission_id
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        handler_result = final_task.metadata_json["handler_result"]
        assert handler_result["handler"] == "tool.invoke"
        assert handler_result["action"] == "retrieval.hybrid_search"
        output = handler_result["output"]
        assert output["real"] is True
        assert output["plugin_required"] is False
        assert output["source"] == "ajenda_brain"
        memory_ids = {str(item.get("id")) for item in output.get("memories", [])}
        assert "mem1" not in memory_ids
        assert "mem2" not in memory_ids
        assert "mission-retrieval-chunk" in memory_ids
        assert PROFILE_ACCOUNT_RECORD_ID in memory_ids or any(
            "Ajenda" in str(item.get("content")) for item in output.get("memories", [])
        )
        evidence_items = handler_result.get("evidence") or []
        assert evidence_items
        business_context = (evidence_items[0].get("provenance") or {}).get("business_context") or {}
        assert business_context.get("business_name") == "Ajenda AI"

        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        assert lineage[0].metadata_json["action"] == "retrieval.hybrid_search"
        assert len(evidence_records) >= 1
        assert evidence_records[0].mission_id == mission_id
        assert redis_client.llen(f"ajenda:queue:{tenant_id_str}:processing") == 0
    finally:
        verify.close()