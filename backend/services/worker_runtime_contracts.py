from typing import Any

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EVIDENCE_CONTRACT_SCHEMA_VERSION, EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_composition.artifact_schemas import (
    ARTIFACT_SCHEMAS_BY_KEY,
    validate_artifact_payload,
)
from backend.services.tools.mission_input_binding import handler_output_for_task


def _mirror_task_output_to_metadata(task_output: dict[str, Any]) -> dict[str, Any]:
    """Project handler output onto task metadata for API/poll consumers."""

    nested_output = task_output.get("output")
    return {
        "handler_result": task_output,
        "output": nested_output if nested_output is not None else task_output,
    }

def _materialized_artifact_reference(task: ExecutionTask, evidence_ids: list[str]) -> list[dict[str, str]]:
    """Attach a durable evidence-backed identity to a declared task artifact."""

    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    contract = metadata.get("expected_output_contract")
    artifact_key = contract.get("artifact") if isinstance(contract, dict) else None
    if not isinstance(artifact_key, str) or not artifact_key.strip() or not evidence_ids:
        return []
    evidence_id = evidence_ids[0]
    return [
        {
            "artifact_id": evidence_id,
            "artifact_key": artifact_key.strip(),
            "evidence_id": evidence_id,
        }
    ]

def _task_action_name(task: ExecutionTask) -> str | None:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    if isinstance(invocation, dict):
        action = invocation.get("action")
        if isinstance(action, str) and action.strip():
            return action.strip()
    return None

def _failure_evidence_record(*, task: ExecutionTask, lease: WorkerLease, worker_id: str, reason: str) -> EvidenceRecord:
    """Build durable evidence for a terminal handler failure.

    Failure evidence is deliberately rejected and never references a successful
    artifact. It lets the runtime graph explain why an artifact was not
    produced while preserving the failed task as the source of truth.
    """

    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    node_key = metadata.get("graph_node_key")
    graph_reference = {
        key: metadata[key] for key in ("graph_version", "graph_fingerprint", "graph_node_key") if key in metadata
    }
    summary = f"Task {task.id} failed: {reason}"[:4000]
    return EvidenceRecord(
        tenant_id=task.tenant_id,
        mission_id=task.mission_id,
        task_graph_node_key=node_key if isinstance(node_key, str) else None,
        materialization_reference=graph_reference or None,
        execution_task_id=task.id,
        # ``validation`` is the schema-approved evidence type for a rejected
        # runtime result; the structured payload carries the failure subtype.
        evidence_type="validation",
        evidence_source="worker_runtime.fail",
        summary=summary,
        structured_payload={
            "task_id": str(task.id),
            "lease_id": str(lease.id),
            "worker_id": worker_id,
            "failure_code": "HANDLER_FAILED",
            "reason": reason,
            "artifact_produced": False,
        },
        artifact_references=[],
        provenance_metadata={
            "runtime_path": "WorkerRuntimeService.fail",
            "tenant_isolation": task.tenant_id,
        },
        trust_signal={"runtime_authoritative": True, "failure_only": True},
        confidence=1.0,
        collection_status="rejected",
        schema_version=EVIDENCE_CONTRACT_SCHEMA_VERSION,
    )

def _validate_declared_output_contract(task: ExecutionTask, task_output: dict[str, Any] | None) -> None:
    """Validate the exact server-declared artifact before task completion.

    Legacy tasks without an output contract retain their existing completion
    behavior. Every declared contract must emit its named artifact. Artifacts
    with a typed schema must also satisfy that structural schema before runtime
    may persist a completed task.
    """

    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw_contract = metadata.get("expected_output_contract")
    if raw_contract is None:
        raw_contract = metadata.get("output_contract")
    if not isinstance(raw_contract, dict) or not raw_contract:
        return

    artifact = raw_contract.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        raise ValueError("declared output contract must include a non-empty artifact")
    artifact_key = artifact.strip()
    if task_output is None:
        raise ValueError(f"completed task must provide output for declared artifact '{artifact_key}'")

    raw_output = task_output.get("output")
    if not isinstance(raw_output, dict):
        raise ValueError(f"completed task must provide output for declared artifact '{artifact_key}'")
    if artifact_key not in raw_output or raw_output[artifact_key] is None:
        raise ValueError(f"completed task must emit declared artifact '{artifact_key}'")

    schema = ARTIFACT_SCHEMAS_BY_KEY.get(artifact_key)
    if schema is None:
        return
    # A public discovery node can be explicitly marked as an intermediate
    # source stage. Its payload is intentionally raw and may contain unresolved
    # identities; research.observe_contacts owns verification before any
    # terminal artifact is materialized. Never infer this from the action name.
    if raw_contract.get("materialization_role") == "intermediate":
        invocation = metadata.get("tool_invocation")
        action = invocation.get("action") if isinstance(invocation, dict) else None
        invocation_input = invocation.get("input") if isinstance(invocation, dict) else None
        if (
            raw_contract.get("allow_empty") is not True
            or action != "web.research"
            or not isinstance(invocation_input, dict)
            or invocation_input.get("include_public_search") is not True
        ):
            raise ValueError("intermediate output contract is only permitted for public web discovery")
        return
    errors = list(validate_artifact_payload(schema, raw_output[artifact_key]))
    if errors:
        artifact_payload = raw_output[artifact_key]
        if isinstance(artifact_payload, dict) and isinstance(artifact_payload.get("error"), str):
            errors.insert(0, f"handler reported failure: {artifact_payload['error'][:500]}")
        research_gap = raw_output.get("research_gap")
        if isinstance(research_gap, str) and research_gap.strip():
            errors.insert(0, f"research gap: {research_gap[:500]}")
        raise ValueError(f"declared artifact '{artifact_key}' failed schema validation: {'; '.join(errors)}")

def _observe_acceptance_reasons(siblings: list[ExecutionTask], *, require_contacts: bool) -> list[str]:
    """Describe incomplete contact coverage without redefining execution success."""

    if not require_contacts:
        return []
    for item in siblings:
        if _task_action_name(item) != "research.observe_contacts":
            continue
        if item.status != ExecutionTaskState.COMPLETED.value:
            continue
        output = handler_output_for_task(item)
        if output.get("accept_met") is True:
            return []
        observed = int(output.get("observed_count", 0) or 0)
        requested = int(output.get("requested_quantity", 0) or 0)
        return [f"requested {requested} observed contacts, produced {observed}"]
    return []

def _mission_acceptance_contract(mission: Any) -> dict[str, Any]:
    raw_metadata = getattr(mission, "metadata_json", None)
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_intake = metadata.get("mission_intake")
    intake: dict[str, Any] = raw_intake if isinstance(raw_intake, dict) else {}
    raw_context = intake.get("context")
    context: dict[str, Any] = raw_context if isinstance(raw_context, dict) else {}
    raw_composition = context.get("composition")
    composition: dict[str, Any] = raw_composition if isinstance(raw_composition, dict) else {}
    contract = composition.get("acceptance_contract")
    return dict(contract) if isinstance(contract, dict) else {}


_TERMINAL_TASK_STATES: frozenset[str] = frozenset(
    {
        ExecutionTaskState.COMPLETED.value,
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.CANCELLED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
        ExecutionTaskState.BLOCKED.value,
    }
)
