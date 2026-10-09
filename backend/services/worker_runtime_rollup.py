from datetime import datetime, UTC
import logging

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.execution_task import ExecutionTask
from backend.repositories.mission_repository import MissionRepository
from backend.runtime.state_machine import InvalidTransitionError
from backend.runtime.transitions import transition_mission, transition_task
from backend.services.mission_acceptance import evaluate_mission_acceptance
from backend.services.mission_composition.deliverable_runtime_read_model import (
    refresh_deliverable_completion_metadata,
)
from backend.services.ontology.algorithms import evaluate_runtime_artifact_completeness
from backend.services.worker_runtime_contracts import (
    _mission_acceptance_contract,
    _observe_acceptance_reasons,
    _TERMINAL_TASK_STATES,
)

logger = logging.getLogger("ajenda.worker_runtime_rollup")

def refresh_deliverable_completion_read_model(service, *, task: ExecutionTask) -> None:
    """Refresh non-authoritative deliverable state without blocking task completion."""

    if task.mission_id is None:
        return
    try:
        mission = MissionRepository(service._session).get_for_tenant(
            mission_id=task.mission_id,
            tenant_id=task.tenant_id,
        )
        if mission is None:
            return
        siblings = service._tasks.list_for_mission(task.mission_id)
        updated_metadata, completion = refresh_deliverable_completion_metadata(
            dict(mission.metadata_json or {}),
            siblings,
        )
        if completion is None:
            return
        mission.metadata_json = updated_metadata
        service._session.add(mission)
    except Exception as exc:
        logger.warning(
            "deliverable_completion_refresh_skipped",
            extra={
                "mission_id": str(task.mission_id),
                "task_id": str(task.id),
                "reason": str(exc),
            },
        )

def maybe_rollup_mission_status(service, *, task: ExecutionTask, worker_id: str) -> None:
    """Advance mission status when graph tasks finish (composition path stays planned today)."""

    if task.mission_id is None:
        return
    mission = MissionRepository(service._session).get_for_tenant(
        mission_id=task.mission_id,
        tenant_id=task.tenant_id,
    )
    if mission is None:
        return
    # Do not reopen terminal missions.
    if mission.status in {
        MissionState.COMPLETED.value,
        MissionState.FAILED.value,
        MissionState.CANCELLED.value,
        MissionState.ARCHIVED.value,
    }:
        return

    siblings = service._tasks.list_for_mission(task.mission_id)
    if not siblings:
        return
    open_tasks = [item for item in siblings if item.status not in _TERMINAL_TASK_STATES]
    failedish = {
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
        ExecutionTaskState.BLOCKED.value,
    }
    # A failed graph node makes every still-open dependent node impossible.
    # Terminalize those descendants now so missions cannot remain running
    # forever behind queued dependency deferrals.
    failed_node_keys = {
        str((item.metadata_json or {}).get("graph_node_key"))
        for item in siblings
        if item.status in failedish
        and isinstance(item.metadata_json, dict)
        and isinstance(item.metadata_json.get("graph_node_key"), str)
    }
    if failed_node_keys:
        changed = False
        for item in siblings:
            if item.status not in {
                ExecutionTaskState.PLANNED.value,
                ExecutionTaskState.QUEUED.value,
                ExecutionTaskState.CLAIMED.value,
            }:
                continue
            deps = (item.metadata_json or {}).get("dependency_keys", [])
            if not isinstance(deps, list) or not failed_node_keys.intersection(str(dep) for dep in deps):
                continue
            transition_task(item, ExecutionTaskState.BLOCKED)
            item.metadata_json = {
                **(item.metadata_json if isinstance(item.metadata_json, dict) else {}),
                "blocked_by_dependency_failure": sorted(failed_node_keys.intersection(str(dep) for dep in deps)),
                "failure": {"code": "DEPENDENCY_FAILED", "retryable": False},
            }
            service._session.add(item)
            changed = True
        if changed:
            service._session.flush()
            # Re-run the same reconciliation so failures propagate through
            # more than one graph edge (A→B→C) in a single worker event.
            service._maybe_rollup_mission_status(task=task, worker_id=worker_id)
            return

    try:
        if open_tasks:
            # First successful completion while others remain → running.
            if mission.status in {
                MissionState.PLANNED.value,
                MissionState.APPROVED.value,
                MissionState.QUEUED.value,
                MissionState.PAUSED.value,
            }:
                transition_mission(mission, MissionState.RUNNING)
                service._session.add(mission)
                service._audit.append(
                    AuditEvent(
                        tenant_id=task.tenant_id,
                        mission_id=task.mission_id,
                        category="mission",
                        action="mission_running",
                        actor=worker_id,
                        details=f"Mission {task.mission_id} marked running after task {task.id}",
                        payload_json={"task_id": str(task.id), "open_tasks": len(open_tasks)},
                    )
                )
            return

        # All graph tasks terminal.
        any_failed = any(item.status in failedish for item in siblings)
        acceptance_contract = _mission_acceptance_contract(mission)
        acceptance_reasons = _observe_acceptance_reasons(
            siblings,
            require_contacts=acceptance_contract.get("require_observed_contacts", True) is True,
        )
        contract_met, contract_reasons = evaluate_mission_acceptance(
            tasks=siblings,
            contract=acceptance_contract,
        )
        for reason in contract_reasons:
            if reason not in acceptance_reasons:
                acceptance_reasons.append(reason)
        acceptance_met = contract_met and not acceptance_reasons
        # A terminal task graph is not a successful product result when a
        # mission declared a durable deliverable whose read model is still
        # incomplete.  The refresh above records this independently of task
        # acceptance; fold that persisted fact into the mission outcome so
        # callers cannot mistake raw terminal output for a usable artifact.
        raw_intake = (
            mission.metadata_json.get("mission_intake") if isinstance(mission.metadata_json, dict) else None
        )
        raw_context = raw_intake.get("context") if isinstance(raw_intake, dict) else None
        raw_composition = raw_context.get("composition") if isinstance(raw_context, dict) else None
        raw_runtime_state = (
            raw_composition.get("deliverable_runtime_state") if isinstance(raw_composition, dict) else None
        )
        raw_completion = raw_runtime_state.get("completion") if isinstance(raw_runtime_state, dict) else None
        if isinstance(raw_runtime_state, dict) and not (
            isinstance(raw_completion, dict) and raw_completion.get("complete") is True
        ):
            acceptance_reasons.append("durable deliverable is incomplete")
            acceptance_met = False
        acceptance_status = "met" if acceptance_met else "partially_met"
        runtime_artifacts: list[str] = []
        for sibling in siblings:
            sibling_metadata = sibling.metadata_json if isinstance(sibling.metadata_json, dict) else {}
            raw_artifacts = sibling_metadata.get("materialized_artifacts") or []
            if not isinstance(raw_artifacts, list):
                continue
            for artifact_ref in raw_artifacts:
                if isinstance(artifact_ref, dict) and isinstance(
                    artifact_key := artifact_ref.get("artifact_key"), str
                ):
                    runtime_artifacts.append(artifact_key)
        runtime_algorithm = evaluate_runtime_artifact_completeness(
            task_count=len(siblings),
            failed_task_count=sum(1 for item in siblings if item.status in failedish),
            acceptance_met=acceptance_met,
            acceptance_reasons=acceptance_reasons,
            materialized_artifact_keys=runtime_artifacts,
        )
        business_outcome_status = None
        for sibling in siblings:
            result = (
                sibling.metadata_json.get("handler_result") if isinstance(sibling.metadata_json, dict) else None
            )
            output = result.get("output") if isinstance(result, dict) else None
            evaluation = output.get("goal_progress_evaluation") if isinstance(output, dict) else None
            if isinstance(evaluation, dict) and isinstance(evaluation.get("status"), str):
                business_outcome_status = evaluation["status"]
        mission.metadata_json = {
            **(mission.metadata_json if isinstance(mission.metadata_json, dict) else {}),
            "acceptance": {
                "status": acceptance_status,
                "scope": "runtime_execution_and_deliverable",
                "business_outcome_status": business_outcome_status,
                "reasons": acceptance_reasons,
                "evaluated_at": datetime.now(UTC).isoformat(),
                "task_count": len(siblings),
                "algorithm_results": [runtime_algorithm.model_dump(mode="json")],
            },
        }
        if not acceptance_met:
            service._audit.append(
                AuditEvent(
                    tenant_id=task.tenant_id,
                    mission_id=task.mission_id,
                    category="mission",
                    action="mission_acceptance_unmet",
                    actor=worker_id,
                    details="; ".join(acceptance_reasons),
                    payload_json={
                        "status": acceptance_status,
                        "reasons": acceptance_reasons,
                        "contract": acceptance_contract,
                    },
                )
            )
        # Mission state reports runtime execution. Deliverable quality is
        # recorded independently above so partial evidence does not erase a
        # successfully executed, persisted, and read-back-verified result.
        # Terminal task execution is not mission success. A mission whose
        # acceptance or deliverable contract is unmet must remain visibly
        # failed so callers cannot mistake raw/intermediate output for a
        # valid product result.
        target = MissionState.FAILED if any_failed or not acceptance_met else MissionState.COMPLETED
        if mission.status != MissionState.RUNNING.value:
            # Hop through running when coming from planned/queued so state machine stays honest.
            if mission.status in {
                MissionState.PLANNED.value,
                MissionState.APPROVED.value,
                MissionState.QUEUED.value,
                MissionState.PAUSED.value,
            }:
                transition_mission(mission, MissionState.RUNNING)
        transition_mission(mission, target)
        service._session.add(mission)
        service._audit.append(
            AuditEvent(
                tenant_id=task.tenant_id,
                mission_id=task.mission_id,
                category="mission",
                action="mission_completed" if target == MissionState.COMPLETED else "mission_failed",
                actor=worker_id,
                details=f"Mission {task.mission_id} rolled up to {target.value} after graph terminalization",
                payload_json={
                    "task_id": str(task.id),
                    "task_count": len(siblings),
                    "mission_status": target.value,
                    "acceptance_status": acceptance_status,
                },
            )
        )
    except InvalidTransitionError as exc:
        logger.warning(
            "mission_status_rollup_skipped",
            extra={
                "mission_id": str(task.mission_id),
                "mission_status": mission.status,
                "reason": str(exc),
            },
        )

