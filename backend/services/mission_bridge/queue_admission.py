"""Runtime queue admission bridge helpers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.domain.mission import (
    MISSION_RUNTIME_QUEUE_ADMISSION_SCHEMA_VERSION,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
)


def current_materialized_execution_task_ids(metadata: dict[str, Any]) -> list[UUID]:
    """Return valid task IDs from the current runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    if task_materialization.get("materialization_status") != "materialized":
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []

    task_ids: list[UUID] = []
    seen_task_ids: set[UUID] = set()
    for raw_task_id in raw_task_ids:
        try:
            task_id = UUID(str(raw_task_id))
        except ValueError:
            continue
        if task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        task_ids.append(task_id)
    return task_ids


def runtime_queue_admission_blocker(
    *, task_id: UUID | None, code: str, message: str, state: str | None = None, reason: str | None = None
) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": code, "message": message}
    if task_id is not None:
        blocker["task_id"] = str(task_id)
    if state is not None:
        blocker["state"] = state
    if reason is not None:
        blocker["reason"] = reason
    return blocker


def runtime_queue_admission_status(*, admitted_task_ids: list[str], blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "admitted"
    if admitted_task_ids:
        return "partially_admitted"
    return "blocked"


def record_reviewed_task_admission(metadata: dict[str, Any], *, task_id: UUID, now: str) -> dict[str, Any]:
    """Reconcile one successful human-reviewed enqueue into the receipt.

    Review approval is a second admission event for the same materialized
    mission graph.  Keep this update tenant/mission scoped, idempotent, and
    limited to the exact reviewed task; unrelated blockers remain evidence.
    """

    updated = dict(metadata)
    task_id_str = str(task_id)
    queued = [str(item) for item in updated.get("queued_execution_task_ids", []) if isinstance(item, str)]
    if task_id_str not in queued:
        queued.append(task_id_str)
    admitted = [str(item) for item in updated.get("admitted_execution_task_ids", []) if isinstance(item, str)]
    if task_id_str not in admitted:
        admitted.append(task_id_str)
    pending = [
        str(item)
        for item in updated.get("pending_review_execution_task_ids", [])
        if isinstance(item, str) and str(item) != task_id_str
    ]
    blockers = [
        dict(blocker)
        for blocker in updated.get("blockers", [])
        if isinstance(blocker, dict) and str(blocker.get("task_id") or "") != task_id_str
    ]
    blocked = [str(blocker["task_id"]) for blocker in blockers if isinstance(blocker.get("task_id"), str)]
    updated.update(
        {
            "queued_execution_task_ids": queued,
            "admitted_execution_task_ids": admitted,
            "pending_review_execution_task_ids": pending,
            "blocked_execution_task_ids": blocked,
            "blockers": blockers,
            "admission_status": runtime_queue_admission_status(admitted_task_ids=admitted, blockers=blockers),
            "updated_at": now,
        }
    )
    return updated


def build_runtime_queue_admission_metadata(
    *,
    mission_id: UUID,
    tenant_id: str,
    materialized_task_ids: list[UUID],
    planned_task_ids: list[str],
    queued_task_ids: list[str],
    already_queued_task_ids: list[str],
    pending_review_task_ids: list[str],
    denied_tasks: list[dict[str, str | None]],
    blockers: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    admitted_task_ids = [*already_queued_task_ids, *queued_task_ids]
    blocked_task_ids = [str(blocker["task_id"]) for blocker in blockers if isinstance(blocker.get("task_id"), str)]
    admission_status = runtime_queue_admission_status(admitted_task_ids=admitted_task_ids, blockers=blockers)
    return {
        "schema_version": MISSION_RUNTIME_QUEUE_ADMISSION_SCHEMA_VERSION,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": admission_status,
        "materialized_execution_task_ids": [str(task_id) for task_id in materialized_task_ids],
        "planned_execution_task_ids": planned_task_ids,
        "queued_execution_task_ids": queued_task_ids,
        "already_queued_execution_task_ids": already_queued_task_ids,
        "admitted_execution_task_ids": admitted_task_ids,
        "pending_review_execution_task_ids": pending_review_task_ids,
        "blocked_execution_task_ids": blocked_task_ids,
        "denied_tasks": denied_tasks,
        "blockers": blockers,
        "runtime_authority": {
            "creates_execution_tasks": False,
            "enqueues_work": True,
            "dispatches_workers": False,
            "executes_adapters": False,
            "calls_task_dispatcher": False,
            "calls_coordinator": True,
        },
        "updated_at": now,
    }


def runtime_queue_admission_response(metadata: dict[str, Any]) -> dict[str, object]:
    return {
        "queued_task_ids": metadata.get("queued_execution_task_ids", []),
        "pending_review_task_ids": metadata.get("pending_review_execution_task_ids", []),
        "denied_tasks": metadata.get("denied_tasks", []),
        "admission_status": metadata.get("admission_status", "blocked"),
        "admitted_task_ids": metadata.get("admitted_execution_task_ids", []),
        "blocked_task_ids": metadata.get("blocked_execution_task_ids", []),
        "blockers": metadata.get("blockers", []),
        "runtime_queue_admission": metadata,
    }
