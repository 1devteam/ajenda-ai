from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest

from backend.services.mission_runtime_evidence_projection import MissionRuntimeEvidenceProjection
from backend.services.runtime_reconciliation_contract import RuntimeReconciliationSnapshot, seal_snapshot
from scripts.validation.mission_information_flow import ReviewedExpectations, build_information_flow, main

_REQUEST = (
    "Find up to three software development companies in Austin, Texas. "
    "Verify each one using its official website and give me a short report with source links."
)
_NODE = "ability-web-research"
_QUERY = "software development companies in Austin"
_SCOPE = [{"type": "company", "industry": "software development", "location": "Austin"}]


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _snapshot(
    *,
    working: bool = False,
    include_interpretation: bool = True,
    status: str | None = None,
    tenant: str = "tenant-a",
    instruction: str = _REQUEST,
) -> RuntimeReconciliationSnapshot:
    mission_id = uuid4()
    scope = {"tenant_id": tenant, "mission_id": str(mission_id)}
    events = [
        {
            **scope,
            "event_id": "confirm",
            "category": "mission_composition",
            "action": "confirmed",
            "runtime_evidence_integrity_verified": True,
            "payload": {
                "runtime_evidence": {"facts": {"instruction_sha256": _fingerprint(instruction), "proposal_id": "p"}}
            },
        },
        {
            **scope,
            "event_id": "start",
            "category": "execution_task",
            "action": "started",
            "task_id": "task-1",
            "runtime_evidence_integrity_verified": True,
        },
        {
            **scope,
            "tenant_id": "foreign",
            "event_id": "foreign-event",
            "category": "execution_task",
            "action": "started",
            "task_id": "task-1",
        },
    ]
    if include_interpretation:
        events.append(
            {
                **scope,
                "event_id": "composition-observation",
                "category": "mission_information",
                "action": "composition_confirmed",
                "payload": {
                    "proposal_id": "p",
                    "semantic_decisions": {
                        "requested_outcomes": ["research_prospects", "synthesize_research_report"]
                        if working
                        else ["research_prospects"],
                    },
                },
            }
        )
    runtime = MissionRuntimeEvidenceProjection(
        tenant_id=tenant,
        mission_id=mission_id,
        mission_status=status or ("completed" if working else "failed"),
        acceptance={"status": "met" if working else "partially_met"},
        nodes=[],
        edges=[],
        available_nodes=[
            {
                "node_key": _NODE,
                "input_contract": {
                    "tool_invocation": {
                        "action": "web.research",
                        "input": {"query": _QUERY if working else "to three " + _QUERY, "limit": 3},
                    }
                },
                "output_contract": {"artifact": "prospect_candidates"},
            }
        ],
        task_flows=[
            {
                "task_id": "task-1",
                "node_key": _NODE,
                "status": "completed",
                "queue_admitted": True,
                "lease_ids": ["lease-1"],
                "evidence_ids": ["evidence-1"],
                "declared_output_contract": {"artifact": "prospect_candidates"},
                "observed_output_keys": ["prospect_candidates"],
                "output_summaries": {"prospect_candidates": {"shape": "list", "count": 9}},
            }
        ],
        execution_events=events,
        first_divergence=None if working else "mission:acceptance",
    )
    return seal_snapshot(
        RuntimeReconciliationSnapshot(
            tenant_id=tenant,
            mission_id=str(mission_id),
            schema_version=2,
            graph_expected_nodes=(_NODE,),
            runtime_evidence=runtime,
        ),
        producer="ajenda.runtime_reconciliation_export",
        producer_version="2",
        source_record_ids=(f"mission:{mission_id}",),
        evidence_contract_version="2",
    )


def _expectations(*, with_scope: bool = False) -> ReviewedExpectations:
    return ReviewedExpectations(
        instruction_sha256=_fingerprint(_REQUEST),
        requested_outcomes=["research_prospects", "synthesize_research_report"],
        target_scope=_SCOPE if with_scope else None,
        planned_actions=["web.research", "research.verify_public_candidates", "research.synthesize_report"],
        planned_inputs={_NODE: {"query": _QUERY, "limit": 3}},
        required_artifacts=["research_report"],
    )


def _record(snapshot: RuntimeReconciliationSnapshot) -> dict:
    semantic = {
        "snapshot_id": "intent-1",
        "tenant_id": snapshot.tenant_id,
        "instruction_sha256": _fingerprint(_REQUEST),
        "target_entities": ({**_SCOPE[0], "industry": "to three software development", "name": "private name"},),
        "requested_outcomes": ("research_prospects",),
    }
    from backend.services.mission_composition.contracts import SemanticSnapshot, _snapshot_digest

    content = SemanticSnapshot.model_construct(**semantic).model_dump(mode="json", exclude={"content_sha256"})
    semantic_snapshot = SemanticSnapshot.model_validate({**content, "content_sha256": _snapshot_digest(content)})
    return {
        "mission_id": snapshot.mission_id,
        "tenant_id": snapshot.tenant_id,
        "intake": {
            "context": {
                "composition": {"proposal_id": "p", "semantic_snapshot": semantic_snapshot.model_dump(mode="json")}
            }
        },
    }


def test_austin_map_finds_interpretation_before_correct_acceptance() -> None:
    snapshot = _snapshot()
    result = build_information_flow(
        snapshot,
        expectations=_expectations(with_scope=True),
        mission_record=_record(snapshot),
        deliverable={"mission_id": snapshot.mission_id, "artifacts": {}, "completion": {"complete": False}},
        instruction=_REQUEST,
        include_values=True,
    )

    assert result["first_supported_mismatch"]["field"] == "target_scope"
    assert result["first_supported_mismatch"]["observed"][0]["industry"] == "to three software development"
    by_field = {check["field"]: check for check in result["checks"]}
    assert by_field["requested_outcomes"]["sources"] == [
        "mission.intake.context.composition.semantic_snapshot.requested_outcomes"
    ]
    assert result["interpretation"]["event_ids"] == ["composition-observation"]
    assert by_field[f"{_NODE}.query"]["observed"] == {"value": "to three " + _QUERY}
    assert by_field[f"{_NODE}.limit"]["status"] == "matched"
    assert by_field["research_report"]["status"] == "mismatch"
    assert result["graft"]["first_recorded_divergence"] == "mission:acceptance"
    assert result["shadow_replay"]["scope"] == "interpreter_replay"
    assert result["read_only"] is True and result["grants_execution_authority"] is False
    assert [event["event_id"] for event in result["tasks"][0]["events"]] == ["start"]
    assert result["tasks"][0]["output_shapes"]["prospect_candidates"]["count"] == 9
    assert "private name" not in json.dumps(result)


def test_unknown_observation_stays_unknown_and_report_redacts_query_by_default() -> None:
    snapshot = _snapshot(include_interpretation=False, status="running")
    result = build_information_flow(
        snapshot,
        expectations=_expectations(with_scope=True),
        deliverable={"mission_id": snapshot.mission_id, "artifacts": {}},
    )

    assert result["first_supported_mismatch"]["field"] == "actions"
    assert result["earlier_unobserved_checks"] == ["target_scope", "requested_outcomes"]
    assert result["checks"][-1]["status"] == "unobserved"
    assert _QUERY not in json.dumps(result)


def test_prior_success_provides_comparisons_for_the_same_instruction() -> None:
    snapshot = _snapshot()
    baseline = _snapshot(working=True)
    result = build_information_flow(snapshot, baseline=baseline)

    assert result["comparison_source"] == f"baseline:{baseline.mission_id}"
    assert result["first_supported_mismatch"]["field"] == "requested_outcomes"
    assert any(item["field"] == f"{_NODE}.query" and item["status"] == "mismatch" for item in result["checks"])


@pytest.mark.parametrize(
    "baseline",
    [_snapshot(), _snapshot(working=True, tenant="different"), _snapshot(working=True, instruction="Other request")],
)
def test_unsuitable_baselines_are_rejected(baseline: RuntimeReconciliationSnapshot) -> None:
    with pytest.raises(ValueError, match="baseline"):
        build_information_flow(_snapshot(), baseline=baseline)


def test_tampered_exports_wrong_mission_and_wrong_replay_are_rejected() -> None:
    snapshot = _snapshot()
    tampered = snapshot.model_copy(update={"graph_expected_nodes": ("unrelated",)})
    with pytest.raises(ValueError, match="digest"):
        build_information_flow(tampered)
    with pytest.raises(ValueError, match="exported mission"):
        build_information_flow(snapshot, deliverable={"mission_id": str(uuid4()), "artifacts": {}})
    with pytest.raises(ValueError, match="confirmed instruction"):
        build_information_flow(snapshot, instruction="Other request")


def test_cli_reads_the_real_export_schema(tmp_path, monkeypatch, capsys) -> None:
    snapshot = _snapshot()
    source = tmp_path / "snapshot.json"
    source.write_text(snapshot.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["mission_information_flow.py", str(source)])

    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mission_id"] == snapshot.mission_id
    assert result["first_supported_mismatch"] is None
    assert result["graft"]["first_recorded_divergence"] == "mission:acceptance"
