from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from backend.domain.execution_task import ExecutionTask
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.mission_runtime_evidence_projection import build_mission_runtime_evidence_projection
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger
from scripts.validation.graph_runtime_impact import build_runtime_impact_artifact


def test_join_preserves_static_runtime_and_unobserved_facts() -> None:
    report = build_runtime_impact_artifact(
        impact_report={
            "schema_version": "1.2",
            "graph_sha256": "graph-hash",
            "changed_files": ["backend/services/example.py"],
            "changed_nodes": [
                {"id": "fn:example:compose", "type": "function", "source": "backend/services/example.py"}
            ],
            "upstream_consumers": [{"id": "runtime:mission", "type": "runtime", "distance": 1}],
            "downstream_dependencies": [],
            "impacted_tests": [{"id": "test:example"}],
            "relevant_invariants": [{"id": "tenant-scope"}],
            "risk_domains": [{"id": "runtime"}],
        },
        runtime_projection={
            "schema_version": 1,
            "mission_id": "mission-1",
            "tenant_id": "tenant-1",
            "available_nodes": [{"node_key": "compose"}, {"node_key": "observe"}],
            "selected_nodes": [{"node_key": "compose"}, {"node_key": "observe"}],
            "task_flows": [
                {"task_id": "task-1", "node_key": "compose", "status": "completed", "lease_ids": ["lease-1"]},
                {"task_id": "task-2", "node_key": "observe", "status": "planned", "queue_admitted": False},
            ],
            "contradictions": ["task:observe:completed_without_evidence"],
            "missing_evidence": ["task:observe:evidence"],
            "first_divergence": "task:evidence",
        },
    )

    facts = report["facts"]
    assert {item["id"] for item in facts["static_affected_nodes"]} == {"fn:example:compose", "runtime:mission"}
    assert facts["runtime_observed_nodes"] == [
        {"id": "compose", "relation": "runtime_observed", "provenance": "mission_runtime_evidence"}
    ]
    assert facts["runtime_materialized_node_keys"] == ["compose", "observe"]
    assert facts["runtime_queue_admitted_node_keys"] == []
    assert facts["runtime_unobserved_selected_nodes"][0]["id"] == "observe"
    assert facts["contradictions"] == ["task:observe:completed_without_evidence"]
    assert facts["unknowns"] == []
    assert report["schema_version"] == "1.1"
    assert report["read_only"] is True
    assert report["authority_class"] == "read_model"
    assert report["grants_execution_authority"] is False


def test_join_names_missing_snapshots_as_unknown_without_adjudicating() -> None:
    report = build_runtime_impact_artifact(impact_report={}, runtime_projection={})

    assert report["facts"]["unknowns"] == ["mission_runtime_evidence_projection", "static_graph_impact_report"]
    assert report["facts"]["contradictions"] == []
    assert report["facts"]["runtime_observed_nodes"] == []


def test_join_preserves_structured_admission_finding_and_ignores_disclaimer_text() -> None:
    report = build_runtime_impact_artifact(
        impact_report={"graph_sha256": "graph-hash"},
        runtime_projection={
            "mission_id": "mission-1",
            "tenant_id": "tenant-1",
            "mission_status": "completed",
            "acceptance": {"status": "met"},
            "contradictions": ["task:task-1:runtime_state_without_queue_admission"],
            "runtime_admission": {"validation_result": {"summary": "No runtime work was queued or dispatched."}},
            "execution_events": [{"details": "No runtime work was queued or dispatched."}],
            "task_flows": [
                {
                    "task_id": "task-1",
                    "status": "completed",
                    "queue_admitted": True,
                    "declared_output_contract": {"artifact": "document_artifact", "artifact_id_required": True},
                    "observed_output_keys": ["document_artifact"],
                    "artifact_ids": [],
                }
            ],
        },
    )

    assert report["facts"]["artifact_linkage_gaps"] == [
        "task:task-1:output_without_artifact_identity:document_artifact"
    ]
    assert report["facts"]["contradictions"] == ["task:task-1:runtime_state_without_queue_admission"]
    assert report["facts"]["runtime_queue_admitted_node_keys"] == []


def test_join_does_not_require_document_ids_for_typed_whole_artifacts() -> None:
    report = build_runtime_impact_artifact(
        impact_report={"graph_sha256": "graph-hash"},
        runtime_projection={
            "task_flows": [
                {
                    "task_id": "task-1",
                    "status": "completed",
                    "queue_admitted": True,
                    "declared_output_contract": {"artifact": "web_page_observation"},
                    "observed_output_keys": ["web_page_observation"],
                    "artifact_ids": [],
                }
            ]
        },
    )

    assert report["facts"]["artifact_linkage_gaps"] == []
    assert report["facts"]["contradictions"] == []


def test_join_distinguishes_materialization_and_queue_receipt_in_the_canonical_projection() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    planned = ExecutionTask(
        id=uuid4(), mission_id=mission_id, tenant_id=tenant_id, status="planned", metadata_json={"node_key": "plan"}
    )
    queued = ExecutionTask(
        id=uuid4(), mission_id=mission_id, tenant_id=tenant_id, status="queued", metadata_json={"node_key": "queue"}
    )
    failed = ExecutionTask(
        id=uuid4(), mission_id=mission_id, tenant_id=tenant_id, status="failed", metadata_json={"node_key": "attempt"}
    )
    audit_repository = Mock(spec=AuditEventRepository)
    audit_repository.append.side_effect = lambda event: event
    with Session() as session:
        started = RuntimeEvidenceLedger(session, audit_repository=audit_repository).append_fact(
            tenant_id=tenant_id,
            mission_id=mission_id,
            category="execution_task",
            action="started",
            producer="worker_runtime",
            actor="worker-1",
            details="Task started under its lease",
            facts={"task_id": str(failed.id)},
        )
    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_admission": {
                "selected_nodes": [{"node_key": "plan"}, {"node_key": "queue"}, {"node_key": "attempt"}],
                "validation_result": {"summary": "No runtime work was queued or dispatched."},
            },
            "runtime_task_materialization": {
                "created_execution_task_ids": [str(planned.id), str(queued.id), str(failed.id)]
            },
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(queued.id)]},
        },
        tasks=[planned, queued, failed],
        leases=[],
        lineage=[],
        evidence=[],
        audit_events=[started],
    )
    facts = build_runtime_impact_artifact(
        impact_report={"graph_sha256": "graph-hash"}, runtime_projection=projection.model_dump(mode="json")
    )["facts"]

    assert facts["runtime_materialized_node_keys"] == ["attempt", "plan", "queue"]
    assert facts["runtime_queue_admitted_node_keys"] == ["queue"]
    assert [item["id"] for item in facts["runtime_observed_nodes"]] == ["attempt"]
    assert [item["id"] for item in facts["runtime_unobserved_selected_nodes"]] == ["plan", "queue"]
    assert f"task:{failed.id}:runtime_state_without_queue_admission" in facts["contradictions"]
    assert "runtime_admission_summary_conflicts_with_observed_queue_execution" not in facts["contradictions"]


@pytest.mark.parametrize(
    ("category", "action", "tenant_id", "mission_id", "verified", "observed"),
    [
        ("execution_task", "started", "tenant-1", "mission-1", True, True),
        ("runtime_evidence", "worker_completion_recorded", "tenant-1", "mission-1", True, True),
        ("execution_task", "started", "tenant-2", "mission-1", True, False),
        ("execution_task", "started", "tenant-1", "mission-2", True, False),
        ("execution_task", "started", "tenant-1", "mission-1", False, False),
        ("execution_task", "claimed", "tenant-1", "mission-1", True, False),
    ],
)
def test_join_requires_scoped_verified_execution_signal_for_failed_tasks(
    category: str, action: str, tenant_id: str, mission_id: str, verified: bool, observed: bool
) -> None:
    report = build_runtime_impact_artifact(
        impact_report={},
        runtime_projection={
            "tenant_id": "tenant-1",
            "mission_id": "mission-1",
            "task_flows": [
                {"node_key": "research", "task_id": "task-1", "status": "failed", "lease_ids": ["lease-1"]},
            ],
            "execution_events": [
                {
                    "category": category,
                    "action": action,
                    "tenant_id": tenant_id,
                    "mission_id": mission_id,
                    "task_id": "task-1",
                    "runtime_evidence_integrity_verified": verified,
                }
            ],
        },
    )

    assert bool(report["facts"]["runtime_observed_nodes"]) is observed
