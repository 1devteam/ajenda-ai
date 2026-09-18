"""Read-only mission runtime evidence projection for GRAFT review.

This module exposes persisted execution facts without adjudicating them.  It is
deliberately a projection over existing mission metadata and runtime tables;
it never queues, claims, starts, retries, or authorizes work.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_composition.deliverable_runtime_artifacts import declared_artifact_key
from backend.services.tools.mission_input_binding import handler_output_for_task


class RuntimeEvidenceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["mission", "task", "queue", "lease", "lineage", "evidence", "artifact"]
    observed_state: str
    expected_state: str | None = None
    tenant_id: str
    references: dict[str, Any] = Field(default_factory=dict)


class RuntimeEvidenceEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    relationship: str
    expected: bool
    observed: bool
    evidence: list[str] = Field(default_factory=list)


class MissionRuntimeEvidenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    mission_id: UUID
    tenant_id: str
    read_only: Literal[True] = True
    grants_execution_authority: Literal[False] = False
    nodes: list[RuntimeEvidenceNode]
    edges: list[RuntimeEvidenceEdge]
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    first_divergence: str | None = None


def _metadata(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    return value if isinstance(value, dict) else {}


def _ids(metadata: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        raw = metadata.get(key)
        if isinstance(raw, list):
            values.update(str(item) for item in raw if isinstance(item, (str, UUID)))
    return values


def _task_artifact_ids(task: ExecutionTask) -> list[str]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw = metadata.get("materialized_artifacts") or metadata.get("artifacts")
    if not isinstance(raw, list):
        return []
    return [str(item.get("artifact_id")) for item in raw if isinstance(item, dict) and item.get("artifact_id")]


def build_mission_runtime_evidence_projection(
    *,
    mission_id: UUID,
    tenant_id: str,
    mission_metadata: dict[str, Any],
    tasks: list[ExecutionTask],
    leases: list[WorkerLease],
    lineage: list[LineageRecord],
    evidence: list[EvidenceRecord],
) -> MissionRuntimeEvidenceProjection:
    """Join persisted mission/runtime facts into a diagnostic GRAFT artifact."""

    nodes: list[RuntimeEvidenceNode] = [
        RuntimeEvidenceNode(
            id=f"mission:{mission_id}",
            kind="mission",
            observed_state="persisted",
            tenant_id=tenant_id,
            references={
                key: value
                for key in (
                    "mission_task_graph",
                    "graph_materialization",
                    "runtime_admission",
                    "runtime_task_materialization",
                    "runtime_queue_admission",
                    "worker_claim_admission",
                    "worker_start_admission",
                    "worker_run_admission",
                )
                if isinstance((value := mission_metadata.get(key)), dict)
            },
        )
    ]
    edges: list[RuntimeEvidenceEdge] = []
    contradictions: list[str] = []
    missing: list[str] = []

    task_by_id = {str(task.id): task for task in tasks if task.tenant_id == tenant_id and task.mission_id == mission_id}
    leases_by_task: dict[str, list[WorkerLease]] = {}
    for lease in leases:
        if lease.tenant_id == tenant_id:
            leases_by_task.setdefault(str(lease.task_id), []).append(lease)
    lineage_by_task: dict[str, list[LineageRecord]] = {}
    for lineage_record in lineage:
        if lineage_record.tenant_id == tenant_id and lineage_record.task_id is not None:
            lineage_by_task.setdefault(str(lineage_record.task_id), []).append(lineage_record)
    evidence_by_task: dict[str, list[EvidenceRecord]] = {}
    for evidence_record in evidence:
        if evidence_record.tenant_id == tenant_id and evidence_record.execution_task_id is not None:
            evidence_by_task.setdefault(str(evidence_record.execution_task_id), []).append(evidence_record)

    queue = _metadata(mission_metadata, "runtime_queue_admission")
    admitted_ids = _ids(queue, "admitted_execution_task_ids", "queued_execution_task_ids")
    materialized_ids = _ids(_metadata(mission_metadata, "runtime_task_materialization"), "created_execution_task_ids")

    mission_node = f"mission:{mission_id}"
    for task_id, task in task_by_id.items():
        task_node = f"task:{task_id}"
        nodes.append(
            RuntimeEvidenceNode(
                id=task_node,
                kind="task",
                observed_state=task.status,
                expected_state="materialized" if task_id in materialized_ids else None,
                tenant_id=tenant_id,
                references={"task_type": (task.metadata_json or {}).get("task_type")},
            )
        )
        edges.append(
            RuntimeEvidenceEdge(
                from_id=mission_node,
                to_id=task_node,
                relationship="materializes",
                expected=True,
                observed=task_id in materialized_ids,
                evidence=[task_id],
            )
        )
        if task_id not in materialized_ids:
            contradictions.append(f"task:{task_id}:exists_without_materialization_reference")

        queue_observed = task_id in admitted_ids or task.status in {
            "queued",
            "claimed",
            "running",
            "completed",
            "failed",
            "dead_lettered",
        }
        nodes.append(
            RuntimeEvidenceNode(
                id=f"queue:{task_id}",
                kind="queue",
                observed_state="admitted" if queue_observed else "missing",
                expected_state="admitted",
                tenant_id=tenant_id,
                references={
                    key: value
                    for key in ("updated_at", "admitted_at", "admission_status")
                    if (value := queue.get(key)) is not None
                },
            )
        )
        edges.append(
            RuntimeEvidenceEdge(
                from_id=task_node,
                to_id=f"queue:{task_id}",
                relationship="admitted_to_queue",
                expected=True,
                observed=queue_observed,
                evidence=["runtime_queue_admission"] if task_id in admitted_ids else [],
            )
        )
        if (
            task.status in {"queued", "claimed", "running", "completed", "failed", "dead_lettered"}
            and task_id not in admitted_ids
        ):
            contradictions.append(f"task:{task_id}:runtime_state_without_queue_admission")

        task_leases = leases_by_task.get(task_id, [])
        if task_leases:
            for lease in task_leases:
                lease_node = f"lease:{lease.id}"
                nodes.append(
                    RuntimeEvidenceNode(
                        id=lease_node,
                        kind="lease",
                        observed_state=lease.status,
                        tenant_id=tenant_id,
                        references={"holder_identity": lease.holder_identity, "task_id": task_id},
                    )
                )
                edges.append(
                    RuntimeEvidenceEdge(
                        from_id=task_node,
                        to_id=lease_node,
                        relationship="claimed_by",
                        expected=task.status in {"claimed", "running", "completed", "failed", "dead_lettered"},
                        observed=True,
                        evidence=[str(lease.id)],
                    )
                )
        elif task.status in {"claimed", "running", "completed", "failed", "dead_lettered"}:
            missing.append(f"task:{task_id}:worker_lease")
            contradictions.append(f"task:{task_id}:state_{task.status}_without_worker_lease")

        for lineage_record in lineage_by_task.get(task_id, []):
            lineage_node = f"lineage:{lineage_record.id}"
            nodes.append(
                RuntimeEvidenceNode(
                    id=lineage_node,
                    kind="lineage",
                    observed_state=lineage_record.relationship_type,
                    tenant_id=tenant_id,
                    references={"relationship_reason": lineage_record.relationship_reason},
                )
            )
            edges.append(
                RuntimeEvidenceEdge(
                    from_id=task_node,
                    to_id=lineage_node,
                    relationship="has_lineage",
                    expected=True,
                    observed=True,
                    evidence=[str(lineage_record.id)],
                )
            )
        task_evidence = evidence_by_task.get(task_id, [])
        for evidence_record in task_evidence:
            evidence_node = f"evidence:{evidence_record.id}"
            nodes.append(
                RuntimeEvidenceNode(
                    id=evidence_node,
                    kind="evidence",
                    observed_state=evidence_record.collection_status,
                    tenant_id=tenant_id,
                    references={
                        "evidence_type": evidence_record.evidence_type,
                        "source": evidence_record.evidence_source,
                    },
                )
            )
            edges.append(
                RuntimeEvidenceEdge(
                    from_id=task_node,
                    to_id=evidence_node,
                    relationship="produces_evidence",
                    expected=True,
                    observed=True,
                    evidence=[str(evidence_record.id)],
                )
            )
        if task.status == "completed" and not task_evidence:
            missing.append(f"task:{task_id}:evidence")
            contradictions.append(f"task:{task_id}:completed_without_evidence")

        expected_artifact = declared_artifact_key(task)
        # Intermediate discovery rows can be intentionally filtered from the
        # deliverable read model. Runtime evidence must still report the raw
        # declared task output as present, otherwise a successful discovery
        # task is falsely diagnosed as artifact loss.
        task_output = handler_output_for_task(task)
        has_declared_output = expected_artifact in task_output if expected_artifact else False
        if task.status == "completed" and expected_artifact and not has_declared_output:
            missing.append(f"task:{task_id}:artifact:{expected_artifact}")
            contradictions.append(f"task:{task_id}:completed_without_artifact:{expected_artifact}")

        for artifact_id in _task_artifact_ids(task):
            artifact_node = f"artifact:{artifact_id}"
            nodes.append(
                RuntimeEvidenceNode(
                    id=artifact_node,
                    kind="artifact",
                    observed_state="referenced",
                    tenant_id=tenant_id,
                    references={"artifact_id": artifact_id},
                )
            )
            edges.append(
                RuntimeEvidenceEdge(
                    from_id=task_node,
                    to_id=artifact_node,
                    relationship="produces_artifact",
                    expected=task.status == "completed",
                    observed=True,
                    evidence=[artifact_id],
                )
            )

    if not tasks:
        missing.append("mission:execution_tasks")
    if tasks and not admitted_ids:
        missing.append("mission:queue_admission")

    first_divergence = None
    for candidate, marker in (
        ("mission:execution_tasks", "mission:execution_tasks"),
        ("mission:queue_admission", "mission:queue_admission"),
        ("task:worker_lease", ":worker_lease"),
        ("task:evidence", ":evidence"),
        ("task:artifact", ":artifact"),
    ):
        if any(item == marker or item.endswith(marker) or f"{marker}:" in item for item in missing):
            first_divergence = candidate
            break

    return MissionRuntimeEvidenceProjection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        nodes=nodes,
        edges=edges,
        contradictions=sorted(set(contradictions)),
        missing_evidence=sorted(set(missing)),
        first_divergence=first_divergence,
    )
