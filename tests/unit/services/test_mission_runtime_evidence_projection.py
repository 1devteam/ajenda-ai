from __future__ import annotations

from datetime import UTC, datetime
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
        metadata={"task_type": "web.research", "runtime_evidence_contract_version": "1"},
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


def test_projection_exposes_terminal_failure_as_first_runtime_divergence() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="failed",
        metadata={
            "task_type": "tool.invoke",
            "runtime_evidence_contract_version": "1",
            "failure": {
                "code": "HANDLER_FAILED",
                "message": "qualified_prospects contained no acceptable rows",
                "failed_at": "2026-09-20T02:08:25Z",
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

    assert projection.first_divergence == "task:execution"
    flow = projection.task_flows[0]
    assert flow["failure"]["code"] == "HANDLER_FAILED"
    assert f"task:{task.id}:failure:HANDLER_FAILED" in projection.contradictions
    assert f"task:{task.id}:evidence" in projection.missing_evidence
    assert f"task:{task.id}:failed_without_evidence" in projection.contradictions


def test_projection_names_declared_artifact_when_completed_output_is_missing() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "runtime_evidence_contract_version": "1",
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


def test_projection_reads_node_key_from_materialization_selection_reference() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "materialization_selection_reference": {"node_key": "ability-web-research"},
            "handler_result": {"output": {"research_report": [{"summary": "observed"}]}},
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

    assert projection.task_flows[0]["node_key"] == "ability-web-research"


def test_projection_exposes_mission_acceptance_facts_without_adjudicating_them() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_status="failed",
        mission_metadata={
            "acceptance": {
                "status": "partially_met",
                "reasons": ["required three drafts, produced two"],
            }
        },
        tasks=[],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert projection.mission_status == "failed"
    assert projection.acceptance["status"] == "partially_met"
    assert projection.acceptance["reasons"] == ["required three drafts, produced two"]


def test_projection_marks_terminal_acceptance_gap_when_tasks_completed() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_status="failed",
        mission_metadata={"acceptance": {"status": "partially_met", "reasons": ["required ten rows, produced eight"]}},
        tasks=[],
        leases=[],
        lineage=[],
        evidence=[],
    )

    assert projection.first_divergence == "mission:acceptance"


def test_projection_exposes_record_lineage_and_ordered_audit_facts() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "handler_result": {
                "output": {
                    "pages": [
                        {
                            "company": "Directory HVAC",
                            "url": "https://directory.example/hvac",
                            "identity_status": "unverified",
                            "source_reliability": "directory_or_third_party",
                        }
                    ],
                    "verified_prospect_candidates": [
                        {
                            "company": "Acme HVAC",
                            "website": "https://acme.example",
                            "identity_status": "verified",
                        }
                    ],
                }
            },
        },
    )
    first = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        category="runtime",
        action="task.claim",
        actor="worker-1",
        details="claimed",
        payload_json={"task_id": str(task.id)},
    )
    second = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        category="runtime",
        action="task.complete",
        actor="worker-1",
        details="completed",
        payload_json={"task_id": str(task.id)},
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={},
        tasks=[task],
        leases=[],
        lineage=[],
        evidence=[],
        audit_events=[second, first],
    )

    assert [item["action"] for item in projection.execution_events] == ["task.claim", "task.complete"]
    assert {item["artifact_key"] for item in projection.record_flows} == {
        "pages",
        "verified_prospect_candidates",
    }
    directory = next(item for item in projection.record_flows if item["artifact_key"] == "pages")
    assert directory["identity_status"] == "unverified"
    assert directory["source_reliability"] == "directory_or_third_party"


def test_projection_preserves_dict_artifact_shape_and_digest() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "tool.invoke",
            "expected_output_contract": {"artifact": "research_report"},
            "handler_result": {"output": {"research_report": {"market_opportunities": [{"title": "one"}]}}},
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
    flow = projection.task_flows[0]
    assert flow["output_summaries"]["research_report"]["shape"] == "dict"
    report_flow = next(item for item in projection.record_flows if item["artifact_key"] == "research_report")
    assert report_flow["value_shape"] == "dict"
    assert report_flow["output_summary"]["sha256"].startswith("sha256:")


def test_unversioned_historical_task_preserves_unknown_without_violation() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(mission_id=mission_id, tenant_id=tenant_id, status="completed")
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
    assert f"task:{task.id}:evidence" in projection.historical_unknown
    assert f"task:{task.id}:evidence" in projection.missing_evidence
    assert f"task:{task.id}:completed_without_evidence" not in projection.contradictions


def test_old_declared_artifact_absence_is_historical_unknown() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "expected_output_contract": {"artifact": "legacy_report"},
            "handler_result": {"output": {}},
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
    assert f"task:{task.id}:artifact:legacy_report" in projection.historical_unknown
    assert f"task:{task.id}:completed_without_artifact:legacy_report" not in projection.contradictions


def test_runtime_projection_exposes_ordered_tenant_scoped_information_flow() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    other_mission_id = uuid4()

    def event(action, day, *, scope=mission_id, tenant=tenant_id):
        return SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant,
            mission_id=scope,
            created_at=datetime(2026, 10, day, tzinfo=UTC),
            category="mission_information",
            action=action,
            actor="observer",
            details="bounded observation",
            payload_json={
                "schema_version": 1,
                "grants_execution_authority": False,
                "input": {"shape": "object", "field_names": ["criteria"]},
            },
        )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={},
        tasks=[],
        leases=[],
        lineage=[],
        evidence=[],
        audit_events=[
            event("execution_completed", 3),
            event("execution_started", 2),
            event("composition_confirmed", 1),
            event("execution_failed", 4, scope=other_mission_id),
            event("execution_failed", 5, tenant="another-tenant"),
            event("execution_failed", 6, scope=None),
        ],
    )
    assert [item["stage"] for item in projection.information_flow] == [
        "composition_confirmed",
        "execution_started",
        "execution_completed",
    ]
    assert all(item["grants_execution_authority"] is False for item in projection.information_flow)
    assert all(item["observation"]["schema_version"] == 1 for item in projection.information_flow)


def test_historical_unknown_evidence_cannot_be_first_proven_divergence() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(mission_id=mission_id, tenant_id=tenant_id, status="completed")
    lease = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        task_id=task.id,
        status="released",
        holder_identity="worker",
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
        evidence=[],
    )
    assert f"task:{task.id}:evidence" in projection.historical_unknown
    assert projection.first_divergence is None


def test_information_coverage_distinguishes_active_missing_from_legacy_unknown() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    current = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={"runtime_evidence_contract_version": "1"},
    )
    legacy = _task(mission_id=mission_id, tenant_id=tenant_id, status="completed")
    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={},
        tasks=[current, legacy],
        leases=[],
        lineage=[],
        evidence=[],
        audit_events=[],
    )
    current_coverage = [entry for entry in projection.information_coverage if entry["scope"] == f"task:{current.id}"]
    legacy_coverage = [entry for entry in projection.information_coverage if entry["scope"] == f"task:{legacy.id}"]
    assert {entry["required_stage"] for entry in current_coverage} == {"execution_started", "execution_completed"}
    assert all(entry["observation"] == "missing_under_active_contract" for entry in current_coverage)
    assert all(entry["observation"] == "not_recorded_or_legacy" for entry in legacy_coverage)


def test_causal_coverage_is_bound_to_the_task_that_emitted_the_observation(monkeypatch) -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    first = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="running",
        metadata={"task_type": "tool.invoke", "runtime_evidence_contract_version": "1"},
    )
    second = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="running",
        metadata={"task_type": "tool.invoke", "runtime_evidence_contract_version": "1"},
    )
    first_lease = SimpleNamespace(
        id=uuid4(), task_id=first.id, tenant_id=tenant_id, status="held", holder_identity="worker-a"
    )
    second_lease = SimpleNamespace(
        id=uuid4(), task_id=second.id, tenant_id=tenant_id, status="held", holder_identity="worker-b"
    )
    event = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        created_at=datetime.now(UTC),
        category="runtime_decision",
        action="input_binding",
        actor="worker-a",
        details="observed",
        payload_json={},
    )
    envelope = SimpleNamespace(
        event_type="runtime_decision.input_binding",
        subject_references={},
        causation_id=str(first_lease.id),
        correlation_id=str(mission_id),
        facts={
            "causal_observation": {
                "stage": "input_binding",
                "decision": "invocation_bound",
                "reason_code": "dependency_binding",
            }
        },
        event_id=event.id,
        occurred_at=datetime.now(UTC),
        producer="worker_runtime",
        evidence_references=(),
    )
    monkeypatch.setattr(
        "backend.services.mission_runtime_evidence_projection.RuntimeEvidenceLedger.read_envelope",
        lambda candidate: envelope if candidate is event else None,
    )

    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(first.id), str(second.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(first.id), str(second.id)]},
        },
        tasks=[first, second],
        leases=[first_lease, second_lease],
        lineage=[],
        evidence=[],
        audit_events=[event],
    )

    first_coverage = [item for item in projection.information_coverage if item["scope"] == f"task:{first.id}"]
    second_coverage = [item for item in projection.information_coverage if item["scope"] == f"task:{second.id}"]
    first_binding = next(item for item in first_coverage if item["required_stage"] == "input_binding")
    second_binding = next(item for item in second_coverage if item["required_stage"] == "input_binding")
    assert first_binding["status"] == "observed"
    assert second_binding["observation"] == "missing_under_active_contract"
    assert f"task:{second.id}:information:input_binding" in projection.missing_evidence
    assert f"task:{first.id}:information:input_binding" not in projection.missing_evidence


def test_non_tool_execution_path_has_no_inapplicable_causal_gaps() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="completed",
        metadata={
            "task_type": "research.synthesize_report",
            "runtime_evidence_contract_version": "1",
            "handler_result": {"output": {"research_report": {"summary": "observed"}}},
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
        leases=[
            SimpleNamespace(
                id=uuid4(), task_id=task.id, tenant_id=tenant_id, status="released", holder_identity="worker"
            )
        ],
        lineage=[],
        evidence=[
            SimpleNamespace(
                id=uuid4(),
                execution_task_id=task.id,
                tenant_id=tenant_id,
                collection_status="collected",
                evidence_type="execution_trace",
                evidence_source="test",
            )
        ],
    )

    assert not any(
        item["required_stage"] in {"input_binding", "provider_selection"} for item in projection.information_coverage
    )
    assert not any(item.startswith(f"task:{task.id}:information:") for item in projection.missing_evidence)


def test_first_divergence_uses_the_earliest_applicable_causal_gap() -> None:
    mission_id = uuid4()
    tenant_id = str(uuid4())
    task = _task(
        mission_id=mission_id,
        tenant_id=tenant_id,
        status="running",
        metadata={"task_type": "tool.invoke", "runtime_evidence_contract_version": "1"},
    )
    projection = build_mission_runtime_evidence_projection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_metadata={
            "runtime_task_materialization": {"created_execution_task_ids": [str(task.id)]},
            "runtime_queue_admission": {"admitted_execution_task_ids": [str(task.id)]},
        },
        tasks=[task],
        leases=[
            SimpleNamespace(id=uuid4(), task_id=task.id, tenant_id=tenant_id, status="held", holder_identity="worker")
        ],
        lineage=[],
        evidence=[],
    )

    assert projection.first_divergence == f"task:{task.id}:information:input_binding"
