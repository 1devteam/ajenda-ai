"""Mission graph/runtime supersession helpers."""

from typing import Any
from uuid import UUID

from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
)
from backend.repositories.execution_task_repository import ExecutionTaskRepository

def _supersede_graph_materialization(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        return
    superseded = dict(materialization)
    superseded["materialization_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = superseded

def _supersede_runtime_admission(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded

def _supersede_runtime_admission_for_materialization(
    *,
    metadata: dict[str, Any],
    materialization_version: int,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "graph_materialization_replaced"
    superseded["superseded_by_materialization_version"] = materialization_version
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded

def _cancel_superseded_materialized_planned_tasks(
    *, metadata: dict[str, Any], task_repo: ExecutionTaskRepository, tenant_id: str, mission_id: UUID
) -> list[str]:
    """Cancel planned ExecutionTask rows referenced by active runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []
    task_ids: list[UUID] = []
    for raw_task_id in raw_task_ids:
        try:
            task_ids.append(UUID(str(raw_task_id)))
        except ValueError:
            continue
    cancelled_tasks = task_repo.cancel_planned_by_ids_for_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=task_ids
    )
    return [str(task.id) for task in cancelled_tasks]
