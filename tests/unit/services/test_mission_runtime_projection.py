from __future__ import annotations

import uuid
from types import SimpleNamespace

from backend.services.mission_runtime_projection import (
    build_execution_task_payload,
    build_runtime_task_materialization_metadata,
    build_runtime_task_preview_items,
    materialization_reference_current,
    runtime_materialization_authority_flags,
)


def test_runtime_projection_preserves_selected_node_order_and_dependency_keys() -> None:
    mission_id = uuid.uuid4()
    readiness = SimpleNamespace(
        graph_reference={
            "graph_version": 3,
            "graph_fingerprint": "sha256:graph",
            "nodes": [
                {"key": "first", "name": "First", "intended_task_type": "collect", "input_contract": {"a": 1}},
                {
                    "key": "second",
                    "name": "Second",
                    "intended_task_type": "draft",
                    "expected_output_contract": {"b": 2},
                },
            ],
            "edges": [{"from_node_key": "first", "to_node_key": "second"}],
        },
        materialization_reference={"materialization_version": 2},
        admission_reference={
            "admission_version": 5,
            "selected_nodes": [
                {"node_key": "first", "runtime_task_type": "collect_runtime"},
                {"node_key": "second", "runtime_task_type": "draft_runtime"},
            ],
        },
    )

    projected = build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)

    assert [item["graph_node_key"] for item in projected] == ["first", "second"]
    assert projected[0]["dependency_keys"] == []
    assert projected[1]["dependency_keys"] == ["first"]
    assert projected[1]["payload_preview"]["admission_version"] == 5
    assert projected[1]["payload_preview"]["materialization_version"] == 2


def test_runtime_projection_preserves_canonical_output_contract() -> None:
    mission_id = uuid.uuid4()
    readiness = SimpleNamespace(
        graph_reference={
            "graph_version": 1,
            "graph_fingerprint": "sha256:graph",
            "nodes": [
                {
                    "key": "research",
                    "name": "Research",
                    "intended_task_type": "tool.invoke",
                    "output_contract": {"artifact": "research_brief"},
                }
            ],
            "edges": [],
        },
        materialization_reference={"materialization_version": 1},
        admission_reference={
            "admission_version": 1,
            "selected_nodes": [{"node_key": "research", "runtime_task_type": "tool.invoke"}],
        },
    )

    projected = build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)

    assert projected[0]["payload_preview"]["expected_output_contract"] == {"artifact": "research_brief"}


def test_execution_task_payload_extends_preview_envelope_with_trace_references() -> None:
    preview_item = {
        "preview_task_key": "mission:m:graph:1:node:n:runtime-task-preview",
        "payload_preview": {"mission_id": "m", "graph_node_key": "n", "runtime_task_type": "collect"},
        "capability_reference": {"capability_id": "capability"},
        "adapter_reference": {"adapter_id": "adapter"},
        "dependency_keys": ["previous"],
        "materialization_selection_reference": {"node_key": "n"},
    }

    payload = build_execution_task_payload(preview_item)

    assert payload["mission_id"] == "m"
    assert payload["graph_node_key"] == "n"
    assert payload["runtime_task_type"] == "collect"
    assert payload["task_type"] == "collect"
    assert payload["capability_reference"] == {"capability_id": "capability"}
    assert payload["adapter_reference"] == {"adapter_id": "adapter"}
    assert payload["dependency_keys"] == ["previous"]
    assert payload["materialization_selection_reference"] == {"node_key": "n"}


def test_execution_task_payload_promotes_tool_invoke_contract_fields() -> None:
    preview_item = {
        "preview_task_key": "mission:m:graph:1:node:n:runtime-task-preview",
        "payload_preview": {
            "mission_id": "m",
            "graph_node_key": "n",
            "runtime_task_type": "tool.invoke",
            "input_contract": {
                "tool_invocation": {"schema_version": 1, "action": "web.search", "input": {"query": "roofing"}},
                "execution_constraints": {"read_only": True},
            },
        },
        "capability_reference": {"capability_id": "capability"},
        "adapter_reference": None,
        "dependency_keys": [],
        "materialization_selection_reference": None,
    }

    payload = build_execution_task_payload(preview_item)

    assert payload["task_type"] == "tool.invoke"
    assert payload["tool_invocation"]["action"] == "web.search"
    assert payload["execution_constraints"] == {"read_only": True}


def test_execution_task_payload_strips_preview_side_effect_authority() -> None:
    preview_item = {
        "preview_task_key": "mission:m:graph:1:node:n:runtime-task-preview",
        "payload_preview": {
            "mission_id": "m",
            "graph_node_key": "n",
            "runtime_task_type": "tool.invoke",
            "input_contract": {
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "gtm.email_send",
                    "input": {"to": "lead@example.com"},
                },
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["gtm.email_send"],
                        "reason": "compiled",
                        "approved_by": "mission_composition_engine",
                    }
                },
            },
        },
        "dependency_keys": [],
    }

    payload = build_execution_task_payload(preview_item)

    assert "execution_constraints" not in payload
    assert "execution_constraints" not in payload["input_contract"]


def test_materialization_metadata_is_current_only_for_matching_active_references() -> None:
    mission_id = uuid.uuid4()
    graph_reference = {"graph_version": 1}
    materialization_reference = {"materialization_version": 1}
    admission_reference = {"admission_version": 1}

    metadata = build_runtime_task_materialization_metadata(
        mission_id=mission_id,
        materialization_version=1,
        created_execution_task_ids=[str(uuid.uuid4())],
        graph_reference=graph_reference,
        materialization_reference=materialization_reference,
        admission_reference=admission_reference,
        materialized_by="tester",
        now="2026-05-09T12:00:00+00:00",
    )

    assert metadata["runtime_authority"] == runtime_materialization_authority_flags()
    assert materialization_reference_current(
        task_materialization=metadata,
        graph_reference=graph_reference,
        materialization_reference=materialization_reference,
        admission_reference=admission_reference,
    )
    metadata["materialization_status"] = "superseded"
    assert not materialization_reference_current(
        task_materialization=metadata,
        graph_reference=graph_reference,
        materialization_reference=materialization_reference,
        admission_reference=admission_reference,
    )
