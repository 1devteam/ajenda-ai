from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_completion import (
    DeliverableCompletion,
    DeliverableFieldCompletion,
    MaterializedArtifact,
)
from backend.services.mission_composition.shadow_preview import (
    build_shadow_preview,
    reconcile_shadow_preview,
)


def _task(*, status: str, action: str) -> ExecutionTask:
    return ExecutionTask(
        id=uuid.uuid4(),
        tenant_id="tenant-shadow",
        mission_id=uuid.uuid4(),
        title=action,
        description=action,
        status=status,
        metadata_json={"tool_invocation": {"action": action}},
    )


def _completion(*, complete: bool) -> DeliverableCompletion:
    return DeliverableCompletion(
        fields=(
            DeliverableFieldCompletion(
                field_key="company_name",
                status="satisfied" if complete else "missing_artifact",
                artifact_keys=("verified_prospect_candidates",),
            ),
        )
    )


def _prospect(name: str) -> dict[str, object]:
    return {
        "company": name,
        "company_name": name,
        "website": f"https://{name.lower()}.example",
        "product_description": "A documented business",
        "research_summary": "Observed in the governed fixture path",
        "sources": ["fixture://source"],
    }


def test_preview_is_non_authoritative_and_records_graph_expectations() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-1",
        preview_id="preview-1",
        task_graph={
            "schema_version": 1,
            "nodes": [
                {
                    "key": "research",
                    "metadata": {"action": "web.research"},
                }
            ],
            "metadata": {},
        },
        planned_artifact_keys=("verified_prospect_candidates",),
        coverage_assessment=None,
        epistemic_context=None,
    )

    assert preview.planned_node_keys == ("research",)
    assert preview.planned_action_names == ("web.research",)
    assert preview.planned_artifact_keys == ("verified_prospect_candidates",)
    assert preview.grants_execution_authority is False


def test_reconciliation_aligns_only_when_runtime_artifact_and_completion_match() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-1",
        preview_id="preview-1",
        task_graph={"nodes": [], "metadata": {}},
        planned_artifact_keys=("verified_prospect_candidates",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="web.research")],
        artifacts=(MaterializedArtifact(artifact_key="verified_prospect_candidates", payload=[_prospect("A")]),),
        completion=_completion(complete=True),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert result.status == "aligned"
    assert result.missing_artifact_keys == ()
    assert result.completed_task_count == 1
    assert result.structural_status == "aligned"
    assert result.schema_status == "aligned"
    assert result.evidence_status == "aligned"
    assert result.semantic_status == "aligned"
    assert result.outcome_status == "aligned"
    assert result.grants_execution_authority is False


def test_reconciliation_exposes_runtime_drift_and_missing_artifacts() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-1",
        preview_id="preview-1",
        task_graph={"nodes": [], "metadata": {}},
        planned_artifact_keys=("verified_prospect_candidates",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="web.research")],
        artifacts=(MaterializedArtifact(artifact_key="unexpected", payload={"value": True}),),
        completion=_completion(complete=False),
    )

    assert result.status == "drifted"
    assert result.missing_artifact_keys == ("verified_prospect_candidates",)
    assert result.unexpected_artifact_keys == ("unexpected",)
    assert result.structural_status == "blocked"
    assert result.schema_status == "not_available"
    assert result.outcome_status == "blocked"


def test_reconciliation_detects_semantic_duplicate_conflict() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-1",
        preview_id="preview-1",
        task_graph={"nodes": [], "metadata": {}},
        planned_artifact_keys=("verified_prospect_candidates",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="web.research")],
        artifacts=(
            MaterializedArtifact(artifact_key="verified_prospect_candidates", payload=[_prospect("A")]),
            MaterializedArtifact(artifact_key="verified_prospect_candidates", payload=[_prospect("B")]),
        ),
        completion=_completion(complete=True),
    )

    assert result.status == "contradictory"
    assert result.semantic_status == "blocked"
    assert result.semantic_mismatch_codes == ("conflicting_duplicate:verified_prospect_candidates",)


def test_reconciliation_detects_conflicting_identity_content_across_artifacts() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-1",
        preview_id="preview-1",
        task_graph={"nodes": [], "metadata": {}},
        planned_artifact_keys=("prospect_candidates", "verified_prospect_candidates"),
        coverage_assessment=None,
        epistemic_context=None,
    )
    first = _prospect("Acme")
    second = {**_prospect("Acme"), "website": "https://different.example"}

    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="web.research")],
        artifacts=(
            MaterializedArtifact(artifact_key="prospect_candidates", payload=[first]),
            MaterializedArtifact(artifact_key="verified_prospect_candidates", payload=[second]),
        ),
        completion=_completion(complete=True),
    )

    assert result.status == "contradictory"
    assert result.semantic_status == "blocked"
    assert result.semantic_mismatch_codes == ("conflicting_identity_website:acme",)


def _goal_graph(objective_key: str = "increase_qualification_score") -> dict[str, object]:
    return {
        "schema_version": 1,
        "nodes": [
            {
                "node_key": "goal-progress",
                "input_contract": {
                    "tool_invocation": {
                        "schema_version": 1,
                        "action": "analysis.evaluate_goal_progress",
                        "input": {
                            "goal": {
                                "goal_id": "mission-goal-1",
                                "objective_key": objective_key,
                                "name": "Improve qualification",
                            },
                            "kpis": [
                                {
                                    "kpi_id": "qualification-score",
                                    "goal_id": "mission-goal-1",
                                    "name": "Qualification score",
                                    "metric": "qualification_score",
                                    "direction": "increase",
                                }
                            ],
                        },
                    }
                },
                "metadata": {"action": "analysis.evaluate_goal_progress"},
            }
        ],
        "metadata": {},
    }


def _goal_artifact(objective_key: str | None) -> MaterializedArtifact:
    payload: dict[str, object] = {
        "status": "insufficient_data",
        "confidence": 0.5,
        "kpi_evaluations": [],
        "progress_gaps": [],
        "evidence_gaps": ["durable_goal_context_unavailable"],
        "explanations": ["Instruction-only evaluation"],
    }
    if objective_key is not None:
        payload["goal_semantic_signature"] = {
            "schema_version": 1,
            "objective_key": objective_key,
            "kpis": [
                {
                    "schema_version": 1,
                    "metric": "qualification_score",
                    "direction": "increase",
                    "normalized_unit": None,
                }
            ],
        }
    return MaterializedArtifact(artifact_key="goal_progress_evaluation", payload=payload)


def test_shadow_preview_preserves_compiled_goal_semantics() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-goal",
        preview_id="preview-goal",
        task_graph=_goal_graph(),
        planned_artifact_keys=("goal_progress_evaluation",),
        coverage_assessment=None,
        epistemic_context=None,
    )

    assert len(preview.expected_goal_semantics) == 1
    assert preview.expected_goal_semantics[0].objective_key == "increase_qualification_score"
    assert preview.expected_goal_semantics[0].kpis[0].metric == "qualification_score"


def test_goal_semantics_align_when_runtime_preserves_owner_signature() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-goal",
        preview_id="preview-goal",
        task_graph=_goal_graph(),
        planned_artifact_keys=("goal_progress_evaluation",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="analysis.evaluate_goal_progress")],
        artifacts=(_goal_artifact("increase_qualification_score"),),
        completion=_completion(complete=True),
    )

    assert result.status == "aligned"
    assert result.semantic_status == "aligned"
    assert result.semantic_drift_codes == ()
    assert result.semantic_mismatch_codes == ()
    assert result.goal_semantic_comparisons == ("equivalent:matching_explicit_objective_key",)


def test_missing_historical_goal_semantics_is_visible_drift_not_contradiction() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-goal",
        preview_id="preview-goal",
        task_graph=_goal_graph(),
        planned_artifact_keys=("goal_progress_evaluation",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="analysis.evaluate_goal_progress")],
        artifacts=(_goal_artifact(None),),
        completion=_completion(complete=True),
    )

    assert result.status == "drifted"
    assert result.semantic_status == "drifted"
    assert result.semantic_drift_codes == ("goal_semantics_not_observed",)
    assert result.semantic_mismatch_codes == ()


def test_non_equivalent_runtime_goal_semantics_is_contradictory() -> None:
    preview = build_shadow_preview(
        proposal_id="proposal-goal",
        preview_id="preview-goal",
        task_graph=_goal_graph(),
        planned_artifact_keys=("goal_progress_evaluation",),
        coverage_assessment=None,
        epistemic_context=None,
    )
    result = reconcile_shadow_preview(
        preview,
        tasks=[_task(status="completed", action="analysis.evaluate_goal_progress")],
        artifacts=(_goal_artifact("increase_revenue"),),
        completion=_completion(complete=True),
    )

    assert result.status == "contradictory"
    assert result.semantic_status == "blocked"
    assert result.semantic_drift_codes == ()
    assert result.semantic_mismatch_codes == ("goal_semantics_conflict:different_explicit_objective_key",)
    assert result.goal_semantic_comparisons == ("not_equivalent:different_explicit_objective_key",)
