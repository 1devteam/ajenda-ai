"""Durable shadow previews and read-only runtime reconciliation.

Shadow previews describe what composition expected before runtime admission.
They are persisted inside the existing mission deliverable state and never
create tasks, resolve credentials, call providers, or grant authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.contracts import CoverageAssessment, EpistemicContext
from backend.services.mission_composition.deliverable_completion import DeliverableCompletion, MaterializedArtifact

ShadowPreviewLifecycle = Literal["current", "superseded", "stale", "contradictory"]
ReconciliationStatus = Literal["not_run", "aligned", "incomplete", "drifted", "contradictory"]


class ShadowPreview(BaseModel):
    """Composition-time expectation persisted as a non-authoritative artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    preview_id: str = Field(min_length=1, max_length=80)
    proposal_id: str = Field(min_length=1, max_length=80)
    created_at: datetime
    lifecycle: ShadowPreviewLifecycle = "current"
    graph_schema_version: int = Field(default=1, ge=1)
    graph_fingerprint: str | None = Field(default=None, max_length=200)
    planned_node_keys: tuple[str, ...] = Field(default=(), max_length=80)
    planned_action_names: tuple[str, ...] = Field(default=(), max_length=80)
    planned_artifact_keys: tuple[str, ...] = Field(default=(), max_length=80)
    required_evidence: tuple[str, ...] = Field(default=(), max_length=80)
    missing_evidence: tuple[str, ...] = Field(default=(), max_length=80)
    coverage_assessment: CoverageAssessment | None = None
    epistemic_context: EpistemicContext | None = None
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False


class RuntimeReconciliation(BaseModel):
    """Comparison of a shadow preview with governed runtime observations."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: ReconciliationStatus = "not_run"
    reconciled_at: datetime | None = None
    expected_artifact_keys: tuple[str, ...] = Field(default=(), max_length=80)
    observed_artifact_keys: tuple[str, ...] = Field(default=(), max_length=80)
    missing_artifact_keys: tuple[str, ...] = Field(default=(), max_length=80)
    unexpected_artifact_keys: tuple[str, ...] = Field(default=(), max_length=80)
    materialized_task_count: int = Field(default=0, ge=0)
    completed_task_count: int = Field(default=0, ge=0)
    completed_deliverable: bool = False
    contradiction_codes: tuple[str, ...] = Field(default=(), max_length=80)
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False


def build_shadow_preview(
    *,
    proposal_id: str,
    task_graph: dict[str, Any],
    planned_artifact_keys: tuple[str, ...],
    coverage_assessment: CoverageAssessment | None,
    epistemic_context: EpistemicContext | None,
    preview_id: str,
    created_at: datetime | None = None,
) -> ShadowPreview:
    """Build a preview from server-owned composition output only."""

    raw_nodes = task_graph.get("nodes", []) if isinstance(task_graph, dict) else []
    nodes = [node for node in raw_nodes if isinstance(node, dict)] if isinstance(raw_nodes, list) else []
    node_keys = tuple(
        sorted(
            {
                str(node.get("node_key") or node.get("key"))
                for node in nodes
                if isinstance(node.get("node_key") or node.get("key"), str)
            }
        )
    )
    actions = tuple(
        sorted(
            {
                str((node.get("metadata") or {}).get("action") or "")
                for node in nodes
                if isinstance(node.get("metadata"), dict)
                and isinstance((node.get("metadata") or {}).get("action"), str)
                and (node.get("metadata") or {}).get("action")
            }
        )
    )
    metadata = task_graph.get("metadata") if isinstance(task_graph, dict) else {}
    graph_schema_version = task_graph.get("schema_version", 1) if isinstance(task_graph, dict) else 1
    graph_fingerprint = metadata.get("graph_fingerprint") if isinstance(metadata, dict) else None
    return ShadowPreview(
        preview_id=preview_id,
        proposal_id=proposal_id,
        created_at=created_at or datetime.now(UTC),
        graph_schema_version=int(graph_schema_version) if isinstance(graph_schema_version, int) else 1,
        graph_fingerprint=graph_fingerprint if isinstance(graph_fingerprint, str) else None,
        planned_node_keys=node_keys,
        planned_action_names=actions,
        planned_artifact_keys=tuple(sorted(set(planned_artifact_keys))),
        required_evidence=tuple(epistemic_context.required_evidence if epistemic_context else ()),
        missing_evidence=tuple(epistemic_context.missing_evidence if epistemic_context else ()),
        coverage_assessment=coverage_assessment,
        epistemic_context=epistemic_context,
    )


def reconcile_shadow_preview(
    preview: ShadowPreview,
    *,
    tasks: list[ExecutionTask],
    artifacts: tuple[MaterializedArtifact, ...],
    completion: DeliverableCompletion,
    contradiction_codes: tuple[str, ...] = (),
    now: datetime | None = None,
) -> RuntimeReconciliation:
    """Compare preview expectations to governed, completed runtime artifacts."""

    observed = tuple(sorted({artifact.artifact_key for artifact in artifacts}))
    expected = tuple(sorted(set(preview.planned_artifact_keys)))
    missing = tuple(sorted(set(expected) - set(observed)))
    unexpected = tuple(sorted(set(observed) - set(expected)))
    completed = sum(1 for task in tasks if str(task.status) == "completed")
    detected_contradictions = tuple(contradiction_codes) + tuple(
        ["runtime_artifact_conflict"]
        if completion.fields and any(field.status == "invalid_artifact" for field in completion.fields)
        else []
    )
    if detected_contradictions:
        status: ReconciliationStatus = "contradictory"
    elif unexpected:
        status = "drifted"
    elif completion.complete and not missing:
        status = "aligned"
    elif artifacts or completed:
        status = "incomplete"
    else:
        status = "not_run"
    return RuntimeReconciliation(
        status=status,
        reconciled_at=now or datetime.now(UTC),
        expected_artifact_keys=expected,
        observed_artifact_keys=observed,
        missing_artifact_keys=missing,
        unexpected_artifact_keys=unexpected,
        materialized_task_count=len(tasks),
        completed_task_count=completed,
        completed_deliverable=completion.complete,
        contradiction_codes=detected_contradictions,
    )
