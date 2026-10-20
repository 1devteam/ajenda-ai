"""Read-only mission runtime evidence projection for GRAFT review.

This module exposes persisted execution facts without adjudicating them.  It is
deliberately a projection over existing mission metadata and runtime tables;
it never queues, claims, starts, retries, or authorizes work.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.audit_event import AuditEvent
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_composition.deliverable_runtime_artifacts import declared_artifact_key
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger
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
    mission_status: str | None = None
    acceptance: dict[str, Any] = Field(default_factory=dict)
    read_only: Literal[True] = True
    grants_execution_authority: Literal[False] = False
    nodes: list[RuntimeEvidenceNode]
    edges: list[RuntimeEvidenceEdge]
    # These sections preserve the planner/runtime boundary for review. They
    # are snapshots of persisted declarations and observations, not judgments.
    available_nodes: list[dict[str, Any]] = Field(default_factory=list)
    selected_nodes: list[dict[str, Any]] = Field(default_factory=list)
    task_flows: list[dict[str, Any]] = Field(default_factory=list)
    record_flows: list[dict[str, Any]] = Field(default_factory=list)
    execution_events: list[dict[str, Any]] = Field(default_factory=list)
    causal_observations: list[dict[str, Any]] = Field(default_factory=list)
    information_flow: list[dict[str, Any]] = Field(default_factory=list)
    information_coverage: list[dict[str, Any]] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    historical_unknown: list[str] = Field(default_factory=list)
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


def _proposal_reference(envelope: Any) -> str | None:
    """Read the durable proposal identity without guessing from event order."""

    facts = envelope.facts if isinstance(getattr(envelope, "facts", None), dict) else {}
    subjects = envelope.subject_references if isinstance(getattr(envelope, "subject_references", None), dict) else {}
    for value in (facts.get("proposal_id"), subjects.get("proposal_id")):
        if isinstance(value, str) and value:
            return value
    if getattr(envelope, "event_type", None) == "mission_composition.confirmed":
        causation_id = getattr(envelope, "causation_id", None)
        if isinstance(causation_id, str) and causation_id:
            return causation_id
    return None


def _execution_path_for_task(task: ExecutionTask | None) -> str | None:
    if task is None or not isinstance(task.metadata_json, dict):
        return None
    metadata = task.metadata_json
    invocation = metadata.get("tool_invocation")
    if isinstance(invocation, dict) and isinstance(invocation.get("action"), str):
        return str(invocation["action"])
    value = _task_node_key(metadata) or metadata.get("task_type")
    return str(value) if isinstance(value, str) and value else None


def _task_artifact_ids(task: ExecutionTask) -> list[str]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw = metadata.get("materialized_artifacts") or metadata.get("artifacts")
    if not isinstance(raw, list):
        return []
    return [str(item.get("artifact_id")) for item in raw if isinstance(item, dict) and item.get("artifact_id")]


def _task_node_key(metadata: dict[str, Any]) -> str | None:
    """Read the canonical materialized node identity from task metadata."""

    for key in ("node_key", "step_key", "job_key"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("materialization_selection_reference", "graph_node_reference"):
        reference = metadata.get(key)
        if not isinstance(reference, dict):
            continue
        value = reference.get("node_key") or reference.get("key")
        if isinstance(value, str) and value:
            return value
    return None


def _output_summary(value: Any) -> dict[str, Any]:
    """Describe an observed handler value without treating it as valid output."""

    if isinstance(value, list):
        shape = "list"
        count = len(value)
        item_types = sorted({type(item).__name__ for item in value})
        keys = sorted({str(key) for item in value if isinstance(item, dict) for key in item})
    elif isinstance(value, dict):
        shape = "dict"
        count = 1
        item_types = []
        keys = sorted(str(key) for key in value)
    elif value is None:
        shape = "null"
        count = 0
        item_types = []
        keys = []
    else:
        shape = type(value).__name__
        count = 1
        item_types = []
        keys = []
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return {
        "shape": shape,
        "count": count,
        "item_types": item_types,
        "keys": keys,
        "sha256": f"sha256:{digest}",
    }


def build_mission_runtime_evidence_projection(
    *,
    mission_id: UUID,
    tenant_id: str,
    mission_metadata: dict[str, Any],
    tasks: list[ExecutionTask],
    leases: list[WorkerLease],
    lineage: list[LineageRecord],
    evidence: list[EvidenceRecord],
    audit_events: list[AuditEvent] | None = None,
    mission_status: str | None = None,
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
    task_flows: list[dict[str, Any]] = []
    record_flows: list[dict[str, Any]] = []
    contradictions: list[str] = []
    missing: list[str] = []
    historical_unknown: list[str] = []

    graph = _metadata(mission_metadata, "mission_task_graph")
    # Composition observations are emitted before a mission exists and are
    # correlated by proposal id.  Only admit those pre-mission events when the
    # confirmed mission carries the same proposal reference; otherwise a
    # tenant-wide audit scan could contaminate this mission's causal history.
    causal_correlations = {str(mission_id)}
    graph_proposal_id = graph.get("proposal_id")
    if isinstance(graph_proposal_id, str) and graph_proposal_id:
        causal_correlations.add(graph_proposal_id)
    raw_intake = mission_metadata.get("mission_intake")
    if isinstance(raw_intake, dict):
        intake_proposal_id = raw_intake.get("proposal_id")
        if isinstance(intake_proposal_id, str) and intake_proposal_id:
            causal_correlations.add(intake_proposal_id)
    # Composition decisions are emitted before a mission exists and are
    # correlated by proposal id.  Confirmation is the durable bridge from
    # that pre-mission proposal to the mission.  Prefer the confirmed fact
    # when older or reduced mission metadata does not retain proposal_id.
    confirmed_proposal_ids: set[str] = set()
    confirmed_without_proposal_id = False
    for event in audit_events or []:
        if event.tenant_id != tenant_id or event.mission_id != mission_id:
            continue
        envelope = RuntimeEvidenceLedger.read_envelope(event)
        if envelope is None or envelope.event_type != "mission_composition.confirmed":
            continue
        proposal_id = _proposal_reference(envelope)
        if proposal_id is not None:
            confirmed_proposal_ids.add(proposal_id)
        else:
            confirmed_without_proposal_id = True
    causal_correlations.update(confirmed_proposal_ids)
    if confirmed_without_proposal_id and not confirmed_proposal_ids and len(causal_correlations) == 1:
        missing.append(f"mission:{mission_id}:information:proposal_identity")
    raw_graph_nodes = graph.get("nodes")
    available_nodes = (
        [dict(node) for node in raw_graph_nodes if isinstance(node, dict)] if isinstance(raw_graph_nodes, list) else []
    )
    admission = _metadata(mission_metadata, "runtime_admission")
    raw_selected_nodes = admission.get("selected_nodes")
    selected_nodes = (
        [dict(node) for node in raw_selected_nodes if isinstance(node, dict)]
        if isinstance(raw_selected_nodes, list)
        else []
    )

    task_by_id = {str(task.id): task for task in tasks if task.tenant_id == tenant_id and task.mission_id == mission_id}
    leases_by_task: dict[str, list[WorkerLease]] = {}
    task_by_lease_id: dict[str, str] = {}
    for lease in leases:
        if lease.tenant_id == tenant_id:
            task_id = str(lease.task_id)
            leases_by_task.setdefault(task_id, []).append(lease)
            task_by_lease_id[str(lease.id)] = task_id
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
    # Versioned audit-ledger facts are an independent durable admission receipt.
    # They supplement (never rewrite) the mission metadata projection and let
    # assurance distinguish a legacy metadata gap from an unadmitted task.
    audited_admitted_ids = {
        envelope.subject_references["task_id"]
        for event in audit_events or []
        if (envelope := RuntimeEvidenceLedger.read_envelope(event)) is not None
        and envelope.event_type in {"execution_task.queued", "runtime_evidence.queue_admission_recorded"}
        and "task_id" in envelope.subject_references
    }
    admitted_ids.update(audited_admitted_ids)
    materialized_ids = _ids(_metadata(mission_metadata, "runtime_task_materialization"), "created_execution_task_ids")
    selected_keys = {
        str(node.get("node_key") or node.get("key"))
        for node in selected_nodes
        if node.get("node_key") or node.get("key")
    }
    for node in available_nodes:
        node_key = str(node.get("node_key") or node.get("key") or "")
        node["selected_for_runtime"] = node_key in selected_keys

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
        evidence_contract_version = (
            task.metadata_json.get("runtime_evidence_contract_version")
            if isinstance(task.metadata_json, dict)
            else None
        )
        if task.status in {"completed", "failed", "dead_lettered"} and not task_evidence:
            missing.append(f"task:{task_id}:evidence")
            if evidence_contract_version == "1":
                contradictions.append(f"task:{task_id}:{task.status}_without_evidence")
            else:
                # The historical contract cannot be reconstructed from absence.
                # Preserve the missing observation without claiming violation.
                historical_unknown.append(f"task:{task_id}:evidence")

        expected_artifact = declared_artifact_key(task)
        # Intermediate discovery rows can be intentionally filtered from the
        # deliverable read model. Runtime evidence must still report the raw
        # declared task output as present, otherwise a successful discovery
        # task is falsely diagnosed as artifact loss.
        task_output = handler_output_for_task(task)
        has_declared_output = expected_artifact in task_output if expected_artifact else False
        if task.status == "completed" and expected_artifact and not has_declared_output:
            marker = f"task:{task_id}:artifact:{expected_artifact}"
            missing.append(marker)
            if evidence_contract_version == "1":
                contradictions.append(f"task:{task_id}:completed_without_artifact:{expected_artifact}")
            else:
                historical_unknown.append(marker)

        for artifact_key, raw_records in task_output.items():
            if isinstance(raw_records, list):
                records: list[tuple[int | None, Any]] = list(enumerate(raw_records))
            else:
                # Reports and other typed artifacts are commonly dict-shaped.
                # Preserve their existence and shape instead of silently dropping
                # them from the evidence graph.
                records = [(None, raw_records)]
            for record_index, raw_record in records:
                if record_index is None and not isinstance(raw_record, dict):
                    record_flows.append(
                        {
                            "task_id": task_id,
                            "artifact_key": str(artifact_key),
                            "record_index": None,
                            "record_id": None,
                            "value_shape": _output_summary(raw_record)["shape"],
                            "value_count": _output_summary(raw_record)["count"],
                            "source_keys": [],
                            "output_summary": _output_summary(raw_record),
                        }
                    )
                    continue
                if not isinstance(raw_record, dict):
                    continue
                record_flows.append(
                    {
                        "task_id": task_id,
                        "artifact_key": str(artifact_key),
                        "record_index": record_index,
                        "record_id": raw_record.get("prospect_id")
                        or raw_record.get("artifact_id")
                        or raw_record.get("url")
                        or raw_record.get("website"),
                        "company": raw_record.get("company"),
                        "website": raw_record.get("website"),
                        "url": raw_record.get("url"),
                        "identity_status": raw_record.get("identity_status"),
                        "source_reliability": raw_record.get("source_reliability"),
                        "reason": raw_record.get("reason"),
                        "source": raw_record.get("source"),
                        "value_shape": "dict",
                        "value_count": 1,
                        "source_keys": sorted(str(key) for key in raw_record),
                        "output_summary": _output_summary(raw_record),
                    }
                )

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

        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        raw_failure = metadata.get("failure")
        failure = dict(raw_failure) if isinstance(raw_failure, dict) else {}
        if task.status == "failed":
            # A terminal failure is a runtime fact in its own right. Preserve
            # the durable dispatcher code/message so the evaluator can locate
            # the first broken edge without inferring it from an empty output.
            failure_code = str(failure.get("code") or "unknown").strip()
            failure_message = str(failure.get("message") or "").strip()
            marker = f"task:{task_id}:failure:{failure_code}"
            contradictions.append(marker)
            if failure_message:
                contradictions.append(f"{marker}:{failure_message[:240]}")
        declared_contract = metadata.get("expected_output_contract")
        if not isinstance(declared_contract, dict):
            declared_contract = metadata.get("output_contract")
        if not isinstance(declared_contract, dict):
            declared_contract = {}
        input_bindings = metadata.get("input_bindings")
        observed_output_keys = sorted(str(key) for key in task_output)
        output_summaries = {str(key): _output_summary(value) for key, value in task_output.items()}
        task_flows.append(
            {
                "task_id": task_id,
                "node_key": _task_node_key(metadata),
                "task_type": metadata.get("task_type"),
                "status": task.status,
                "input_bindings": [dict(item) for item in input_bindings if isinstance(item, dict)]
                if isinstance(input_bindings, list)
                else [],
                "declared_output_contract": dict(declared_contract),
                "observed_output_keys": observed_output_keys,
                "output_summaries": output_summaries,
                "failure": failure,
                "queue_admitted": task_id in admitted_ids
                or task.status
                in {
                    "queued",
                    "claimed",
                    "running",
                    "completed",
                    "failed",
                    "dead_lettered",
                },
                "lease_ids": [str(item.id) for item in leases_by_task.get(task_id, [])],
                "lineage_ids": [str(item.id) for item in lineage_by_task.get(task_id, [])],
                "evidence_ids": [str(item.id) for item in evidence_by_task.get(task_id, [])],
                "evidence_collection_statuses": [
                    {"evidence_id": str(item.id), "collection_status": item.collection_status}
                    for item in evidence_by_task.get(task_id, [])
                ],
                "artifact_ids": _task_artifact_ids(task),
            }
        )

    if not tasks:
        missing.append("mission:execution_tasks")
    if tasks and not admitted_ids:
        missing.append("mission:queue_admission")

    first_divergence = None
    acceptance_status = str(_metadata(mission_metadata, "acceptance").get("status") or "").strip().lower()
    if mission_status in {"failed", "blocked"} and acceptance_status in {"failed", "partially_met"}:
        # A mission may have every task reach a terminal state and still fail
        # its declared minimum-row/schema acceptance. Preserve that boundary
        # as a fact when no earlier task execution failure explains it.
        first_divergence = "mission:acceptance"
    for candidate, marker in (
        ("mission:execution_tasks", "mission:execution_tasks"),
        ("mission:queue_admission", "mission:queue_admission"),
        ("task:execution", ":failure:"),
        ("task:worker_lease", ":worker_lease"),
        ("task:evidence", ":evidence"),
        ("task:artifact", ":artifact"),
    ):
        if first_divergence is not None and candidate != "task:execution":
            continue
        if candidate == "task:execution":
            if any(marker in item for item in contradictions):
                first_divergence = candidate
                break
        elif any(
            (item == marker or item.endswith(marker) or f"{marker}:" in item) and item not in historical_unknown
            for item in missing
        ):
            first_divergence = candidate
            break

    execution_events: list[dict[str, Any]] = []
    for event in sorted(audit_events or [], key=lambda item: item.created_at):
        if event.tenant_id != tenant_id or event.mission_id != mission_id:
            continue
        envelope = RuntimeEvidenceLedger.read_envelope(event)
        subjects = envelope.subject_references if envelope is not None else {}
        event_task_id: str | None = (
            subjects.get("task_id") or task_by_lease_id.get(envelope.causation_id or "") if envelope else None
        )
        event_task = task_by_id.get(event_task_id) if isinstance(event_task_id, str) else None
        execution_events.append(
            {
                "event_id": str(event.id),
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "category": event.category,
                "action": event.action,
                "actor": event.actor,
                "details": event.details,
                "payload": event.payload_json,
                # The event payload remains the producer-owned historical
                # record. These normalized references make joins explicit for
                # read-only consumers without treating absent legacy fields as
                # evidence that the underlying work never happened.
                "tenant_id": tenant_id,
                "mission_id": str(getattr(envelope, "mission_id", None) or mission_id)
                if envelope is not None
                else str(mission_id),
                "proposal_id": _proposal_reference(envelope) if envelope is not None else None,
                "task_id": event_task_id,
                "lease_id": subjects.get("lease_id"),
                "execution_path": _execution_path_for_task(event_task),
                "causation_id": envelope.causation_id if envelope is not None else None,
                "correlation_id": envelope.correlation_id if envelope is not None else None,
                "runtime_evidence_integrity_verified": envelope is not None,
            }
        )

    causal_observations: list[dict[str, Any]] = []
    for event in sorted(audit_events or [], key=lambda item: item.created_at):
        if event.tenant_id != tenant_id or (event.mission_id is not None and event.mission_id != mission_id):
            continue
        envelope = RuntimeEvidenceLedger.read_envelope(event)
        if envelope is None:
            continue
        if event.mission_id is None and envelope.correlation_id not in causal_correlations:
            continue
        raw = envelope.facts.get("causal_observation")
        if not isinstance(raw, dict):
            continue
        observation_task_id: str | None = envelope.subject_references.get("task_id") or task_by_lease_id.get(
            envelope.causation_id or ""
        )
        observation_task = task_by_id.get(observation_task_id) if isinstance(observation_task_id, str) else None
        proposal_id = _proposal_reference(envelope)
        # Pre-mission composition observations are linked by the confirmed
        # proposal fact above.  Do not claim a proposal identity when that
        # bridge is absent.
        if (
            proposal_id is None
            and event.mission_id is None
            and envelope.correlation_id in causal_correlations
            and envelope.correlation_id != str(mission_id)
        ):
            proposal_id = envelope.correlation_id
        causal_observations.append(
            {
                **raw,
                # Causal records are linked to the execution path through the
                # lease that caused them.  Keep that identity in the
                # projection so one task's observation cannot satisfy another
                # task's contract.
                "tenant_id": tenant_id,
                "mission_id": str(getattr(envelope, "mission_id", None) or mission_id),
                "proposal_id": proposal_id,
                "plan_id": envelope.subject_references.get("plan_id"),
                "task_id": observation_task_id,
                "lease_id": envelope.subject_references.get("lease_id"),
                "execution_path": _execution_path_for_task(observation_task),
                "contract_version": (
                    observation_task.metadata_json.get("runtime_evidence_contract_version")
                    if observation_task is not None and isinstance(observation_task.metadata_json, dict)
                    else None
                ),
                "event_id": str(envelope.event_id),
                "occurred_at": envelope.occurred_at.isoformat(),
                "producer": envelope.producer,
                "causation_id": envelope.causation_id,
                "correlation_id": envelope.correlation_id,
                "evidence_references": list(envelope.evidence_references),
            }
        )
    information_flow = [
        {
            "stage": observation.get("stage"),
            "decision": observation.get("decision"),
            "reason_code": observation.get("reason_code"),
            "transformation_id": observation.get("transformation_id"),
            "selected_path": observation.get("selected_path"),
            "rejected_paths": observation.get("rejected_paths", []),
            "field_lineage": observation.get("field_lineage", {}),
            "source_provenance": observation.get("source_provenance", {}),
            "event_id": observation.get("event_id"),
            "tenant_id": observation.get("tenant_id"),
            "mission_id": observation.get("mission_id"),
            "proposal_id": observation.get("proposal_id"),
            "task_id": observation.get("task_id"),
            "lease_id": observation.get("lease_id"),
            "execution_path": observation.get("execution_path"),
            "contract_version": observation.get("contract_version"),
        }
        for observation in causal_observations
    ]
    # Preserve the legacy lifecycle observations alongside the richer causal
    # records. They are facts emitted by the runtime, not retrospective
    # explanations, and remain useful for older missions.
    information_flow.extend(
        {
            "event_id": event["event_id"],
            "created_at": event["created_at"],
            "stage": event["action"],
            "producer": event["actor"],
            "observation": event["payload"],
            "grants_execution_authority": False,
        }
        for event in execution_events
        if event["category"] == "mission_information"
        and isinstance(event["payload"], dict)
        and event["action"]
        in {
            "composition_confirmed",
            "execution_started",
            "execution_completed",
            "execution_failed",
            "execution_completion_blocked",
        }
    )
    observed_stages_by_task: dict[str, set[str]] = {}
    for item in causal_observations:
        task_ref = item.get("task_id")
        if isinstance(task_ref, str) and task_ref in task_by_id:
            observed_stages_by_task.setdefault(task_ref, set()).add(str(item.get("stage")))
    for item in information_flow:
        observation = item.get("observation")
        task_ref = observation.get("task_id") if isinstance(observation, dict) else None
        if isinstance(task_ref, str) and task_ref in task_by_id:
            observed_stages_by_task.setdefault(task_ref, set()).add(str(item.get("stage")))

    information_coverage: list[dict[str, Any]] = []
    causal_gap_markers: list[str] = []
    for task in tasks:
        if task.tenant_id != tenant_id or task.mission_id != mission_id:
            continue
        metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
        task_id = str(task.id)
        contract_version = metadata.get("runtime_evidence_contract_version")
        applicable = contract_version == "1"
        stages = observed_stages_by_task.get(task_id, set())
        task_output = handler_output_for_task(task)
        tool_invocation = metadata.get("tool_invocation")
        action = tool_invocation.get("action") if isinstance(tool_invocation, dict) else metadata.get("action")
        is_tool_path = metadata.get("task_type") == "tool.invoke" or isinstance(action, str)
        path_name = _task_node_key(metadata) or str(action or metadata.get("task_type") or "unknown")
        terminal_or_started = task.status in {
            "running",
            "completed",
            "failed",
            "blocked",
            "dead_lettered",
        }
        required_causal_stages: list[str] = []
        # Legacy tasks without an active evidence contract cannot be treated
        # as missing a contract that was never attached to their execution.
        if applicable and is_tool_path and terminal_or_started:
            required_causal_stages.extend(("input_binding", "provider_selection"))
        if task.status == "completed" and is_tool_path:
            required_causal_stages.append("output_validation")
            if task_output:
                required_causal_stages.append("tool_output")
            if isinstance(task_output.get("source_partitions"), dict):
                required_causal_stages.append("source_partition")
        for required_stage, relevant in (
            ("execution_started", task.status in {"running", "completed", "failed", "blocked", "dead_lettered"}),
            ("execution_completed", task.status == "completed"),
            ("execution_failed", task.status == "failed"),
            ("execution_completion_blocked", task.status == "blocked"),
        ):
            if not relevant:
                continue
            information_coverage.append(
                {
                    "scope": f"task:{task_id}",
                    "task_id": task_id,
                    "execution_path": path_name,
                    "contract_version": contract_version,
                    "applicable": True,
                    "applicability_reason": "lifecycle_stage_reached",
                    "required_stage": required_stage,
                    "stage": required_stage,
                    "observation": (
                        "recorded"
                        if required_stage in stages
                        else "missing_under_active_contract"
                        if applicable
                        else "not_recorded_or_legacy"
                    ),
                    "status": "observed" if required_stage in stages else "not_observed",
                    "source": "mission_information_audit",
                }
            )
        for required_stage in required_causal_stages:
            observed = required_stage in stages
            marker = f"task:{task_id}:information:{required_stage}"
            information_coverage.append(
                {
                    "scope": f"task:{task_id}",
                    "task_id": task_id,
                    "execution_path": path_name,
                    "contract_version": contract_version,
                    "applicable": True,
                    "applicability_reason": "tool_execution_path_under_active_contract"
                    if applicable
                    else "tool_execution_path_without_active_contract",
                    "required_stage": required_stage,
                    "stage": required_stage,
                    "status": "observed" if observed else "not_observed",
                    "observation": (
                        "recorded"
                        if observed
                        else "missing_under_active_contract"
                        if applicable
                        else "not_recorded_or_legacy"
                    ),
                    "source": "runtime_decision.audit_events",
                }
            )
            if not observed:
                causal_gap_markers.append(marker)
                (missing if applicable else historical_unknown).append(marker)

    # A causal gap is an execution-path finding, never a mission-wide one.
    # It participates only when no earlier structural break (for example a
    # missing lease) already explains why the path could not proceed.
    if causal_gap_markers and (first_divergence is None or first_divergence == "mission:acceptance"):
        first_divergence = causal_gap_markers[0]

    return MissionRuntimeEvidenceProjection(
        mission_id=mission_id,
        tenant_id=tenant_id,
        mission_status=mission_status,
        acceptance=_metadata(mission_metadata, "acceptance"),
        nodes=nodes,
        edges=edges,
        available_nodes=available_nodes,
        selected_nodes=selected_nodes,
        task_flows=task_flows,
        record_flows=record_flows,
        execution_events=execution_events,
        causal_observations=causal_observations,
        information_flow=information_flow,
        information_coverage=information_coverage,
        contradictions=sorted(set(contradictions)),
        missing_evidence=sorted(set(missing)),
        historical_unknown=sorted(set(historical_unknown)),
        first_divergence=first_divergence,
    )
