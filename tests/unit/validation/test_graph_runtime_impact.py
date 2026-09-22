from __future__ import annotations

import importlib.util
from pathlib import Path

PATH = Path(__file__).parents[3] / "scripts" / "validation" / "graph_runtime_impact.py"
SPEC = importlib.util.spec_from_file_location("graph_runtime_impact", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_join_preserves_static_runtime_and_unobserved_facts() -> None:
    report = MODULE.build_runtime_impact_artifact(
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
            "task_flows": [{"node_key": "compose", "status": "completed"}],
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
    assert facts["runtime_unobserved_selected_nodes"][0]["id"] == "observe"
    assert facts["contradictions"] == ["task:observe:completed_without_evidence"]
    assert facts["unknowns"] == []
    assert report["read_only"] is True
    assert report["grants_execution_authority"] is False


def test_join_names_missing_snapshots_as_unknown_without_adjudicating() -> None:
    report = MODULE.build_runtime_impact_artifact(impact_report={}, runtime_projection={})

    assert report["facts"]["unknowns"] == ["mission_runtime_evidence_projection", "static_graph_impact_report"]
    assert report["facts"]["contradictions"] == []
    assert report["facts"]["runtime_observed_nodes"] == []


def test_join_exposes_artifact_identity_gap_and_stale_admission_summary() -> None:
    report = MODULE.build_runtime_impact_artifact(
        impact_report={"graph_sha256": "graph-hash"},
        runtime_projection={
            "mission_id": "mission-1",
            "tenant_id": "tenant-1",
            "mission_status": "completed",
            "acceptance": {"status": "met"},
            "runtime_admission": {
                "validation_result": {"summary": "No runtime work was queued or dispatched."},
            },
            "task_flows": [
                {
                    "task_id": "task-1",
                    "status": "completed",
                    "queue_admitted": True,
                    "declared_output_contract": {"artifact": "web_page_observation"},
                    "observed_output_keys": ["web_page_observation"],
                    "artifact_ids": [],
                }
            ],
        },
    )

    assert report["facts"]["artifact_linkage_gaps"] == [
        "task:task-1:output_without_artifact_identity:web_page_observation"
    ]
    assert report["facts"]["contradictions"] == ["runtime_admission_summary_conflicts_with_observed_queue_execution"]
