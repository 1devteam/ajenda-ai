"""Collect runtime task outputs into deliverable-completion artifacts.

This module is descriptive only. It reads already-completed task outputs and the
server-owned expected output contracts attached to those tasks. It does not
complete tasks, mutate missions, reinterpret instructions, select jobs, or grant
execution authority.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.mission_composition.deliverable_completion import MaterializedArtifact
from backend.services.tools.mission_input_binding import handler_output_for_task


def declared_artifact_key(task: ExecutionTask) -> str | None:
    """Return the server-declared artifact key for a materialized task."""

    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    raw_contract = metadata.get("expected_output_contract")
    if raw_contract is None:
        raw_contract = metadata.get("output_contract")
    if not isinstance(raw_contract, dict):
        return None
    artifact = raw_contract.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        return None
    return artifact.strip()


def materialized_artifact_for_task(task: ExecutionTask) -> MaterializedArtifact | None:
    """Project one completed task onto its declared artifact, if actually present."""

    if task.status != ExecutionTaskState.COMPLETED.value:
        return None
    artifact_key = declared_artifact_key(task)
    if artifact_key is None:
        return None
    output = handler_output_for_task(task)
    if artifact_key not in output:
        return None
    payload = output[artifact_key]
    if payload is None:
        return None
    return MaterializedArtifact(artifact_key=artifact_key, payload=payload)


def collect_materialized_artifacts(tasks: list[ExecutionTask]) -> tuple[MaterializedArtifact, ...]:
    """Collect unique declared artifacts, failing closed on conflicting duplicates.

    Re-runs may leave more than one completed task with the same declared artifact.
    Identical payloads collapse safely. Conflicting payloads are omitted rather than
    selecting an arbitrary winner, which leaves the requested deliverable incomplete.
    """

    grouped: dict[str, list[Any]] = defaultdict(list)
    for task in sorted(tasks, key=lambda item: str(item.id)):
        artifact = materialized_artifact_for_task(task)
        if artifact is not None:
            grouped[artifact.artifact_key].append(artifact.payload)

    collected: list[MaterializedArtifact] = []
    for artifact_key in sorted(grouped):
        payloads = grouped[artifact_key]
        first = payloads[0]
        if any(payload != first for payload in payloads[1:]):
            continue
        collected.append(MaterializedArtifact(artifact_key=artifact_key, payload=first))
    return tuple(collected)
