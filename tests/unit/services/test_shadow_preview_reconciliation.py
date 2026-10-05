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
