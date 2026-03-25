"""
Execution Coordinator

Lightweight coordination seam for governed execution.

Current incremental stage:
- additive only
- no orchestration migration yet
- registry retained as a transitional live-process cache
- no scheduler / saga rewrite

Purpose:
- provide a stable place for mission/fleet/task/branch coordination metadata
- prevent MissionExecutor from becoming the long-term coordination hub
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.domain.control.repositories.execution_runtime_repository import (
    ExecutionRuntimeRepository,
)
from backend.domain.control.services.execution_registry import ExecutionRegistry
from backend.models.domain.execution_branch import ExecutionBranch
from backend.models.domain.execution_task import ExecutionTask
from backend.models.domain.workforce_fleet import WorkforceFleet


class ExecutionCoordinator:
    """
    Control-layer coordination seam for governed execution state.

    This service is intentionally lightweight in the current phase.
    It does not execute missions itself. It normalizes coordination metadata
    and provides a future home for orchestration policies.
    """

    def __init__(
        self,
        registry: Optional[ExecutionRegistry] = None,
        runtime_repository: Optional[ExecutionRuntimeRepository] = None,
    ) -> None:
        self.registry = registry or ExecutionRegistry()
        self.runtime_repository = runtime_repository

    def _has_durable_runtime(self) -> bool:
        """Return True when durable runtime persistence is available."""
        return self.runtime_repository is not None

    def build_execution_context(
        self,
        *,
        mission_id: str,
        tenant_id: str,
        objective: str,
        fleet: Optional[WorkforceFleet] = None,
        task: Optional[ExecutionTask] = None,
        branch: Optional[ExecutionBranch] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = metadata or {}

        if fleet:
            self.registry.register_fleet(fleet)
            if self.runtime_repository:
                self.runtime_repository.save_fleet(fleet)
        if task:
            self.registry.register_task(task)
            if self.runtime_repository:
                self.runtime_repository.save_task(task)
        if branch:
            self.registry.register_branch(branch)
            if self.runtime_repository:
                self.runtime_repository.save_branch(branch)

        return {
            "mission_id": mission_id,
            "tenant_id": tenant_id,
            "objective": objective,
            "fleet_id": fleet.id if fleet else None,
            "task_id": task.id if task else None,
            "branch_id": branch.id if branch else None,
            "fleet": fleet.model_dump() if fleet else None,
            "task": task.model_dump() if task else None,
            "branch": branch.model_dump() if branch else None,
            "metadata": metadata,
        }


    def build_task_execution_context(
        self,
        *,
        mission_id: str,
        tenant_id: str,
        objective: str,
        task: ExecutionTask,
        fleet: Optional[WorkforceFleet] = None,
        branch_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Transitional helper for executor-owned task execution context assembly.

        Purpose:
        - keep task creation in MissionExecutor for now
        - move governed context registration/assembly into control layer
        """
        context = self.build_execution_context(
            mission_id=mission_id,
            tenant_id=tenant_id,
            objective=objective,
            fleet=fleet,
            task=task,
            metadata=metadata,
        )
        if branch_id:
            context["branch_id"] = branch_id
        return context

    def get_authoritative_mission_execution_state(self, mission_id: str) -> Dict[str, Any]:
        """
        Return the authoritative governed execution state for a mission.

        Transitional seam:
        - durable repository first
        - registry fallback retained only as ephemeral compatibility behavior
        """
        return self.get_execution_state_for_mission(mission_id)

    def attach_fleet(
        self,
        context: Dict[str, Any],
        fleet: WorkforceFleet,
    ) -> Dict[str, Any]:
        self.registry.register_fleet(fleet)
        if self.runtime_repository:
            self.runtime_repository.save_fleet(fleet)
        updated = dict(context)
        updated["fleet_id"] = fleet.id
        updated["fleet"] = fleet.model_dump()
        return updated

    def attach_task(
        self,
        context: Dict[str, Any],
        task: ExecutionTask,
    ) -> Dict[str, Any]:
        self.registry.register_task(task)
        if self.runtime_repository:
            self.runtime_repository.save_task(task)
        updated = dict(context)
        updated["task_id"] = task.id
        updated["task"] = task.model_dump()
        return updated

    def attach_branch(
        self,
        context: Dict[str, Any],
        branch: ExecutionBranch,
    ) -> Dict[str, Any]:
        self.registry.register_branch(branch)
        if self.runtime_repository:
            self.runtime_repository.save_branch(branch)
        updated = dict(context)
        updated["branch_id"] = branch.id
        updated["branch"] = branch.model_dump()
        return updated

    def get_execution_state_for_mission(self, mission_id: str) -> Dict[str, Any]:
        """
        Return governed execution objects for a mission.

        Authority policy:
        - durable runtime repository is primary
        - registry is ephemeral compatibility fallback only
        """
        if self._has_durable_runtime():
            fleets = self.runtime_repository.list_fleets_for_mission(mission_id)
            tasks = self.runtime_repository.list_tasks_for_mission(mission_id)
            branches = self.runtime_repository.list_branches_for_mission(mission_id)

            return {
                "mission_id": mission_id,
                "fleets": [self._fleet_record_to_dict(fleet) for fleet in fleets],
                "tasks": [self._task_record_to_dict(task) for task in tasks],
                "branches": [self._branch_record_to_dict(branch) for branch in branches],
                "source": "runtime_repository",
            }

        fleets = self.registry.list_fleets_for_mission(mission_id)
        tasks = self.registry.list_tasks_for_mission(mission_id)
        branches = self.registry.list_branches_for_mission(mission_id)

        return {
            "mission_id": mission_id,
            "fleets": [fleet.model_dump() for fleet in fleets],
            "tasks": [task.model_dump() for task in tasks],
            "branches": [branch.model_dump() for branch in branches],
            "source": "registry",
        }

    def get_fleet_tasks(self, fleet_id: str) -> Dict[str, Any]:
        """
        Return a fleet and its tasks.

        Authority policy:
        - durable runtime repository is primary
        - registry is ephemeral compatibility fallback only
        """
        if self._has_durable_runtime():
            fleet = self.runtime_repository.get_fleet(fleet_id)
            tasks = self.runtime_repository.list_tasks_for_fleet(fleet_id)

            return {
                "fleet_id": fleet_id,
                "fleet": self._fleet_record_to_dict(fleet) if fleet else None,
                "tasks": [self._task_record_to_dict(task) for task in tasks],
                "source": "runtime_repository",
            }

        fleet = self.registry.get_fleet(fleet_id)
        tasks = self.registry.list_tasks_for_fleet(fleet_id)

        return {
            "fleet_id": fleet_id,
            "fleet": fleet.model_dump() if fleet else None,
            "tasks": [task.model_dump() for task in tasks],
            "source": "registry",
        }

    def _fleet_record_to_dict(self, record: Any) -> Dict[str, Any]:
        return {
            "id": record.id,
            "mission_id": record.mission_id,
            "tenant_id": record.tenant_id,
            "status": record.status,
            "fleet_type": record.fleet_type,
            "objective": record.objective,
            "primary_agent_id": record.primary_agent_id,
            "branch_id": record.branch_id,
            "parent_fleet_id": record.parent_fleet_id,
            "agent_ids": list(record.agent_ids or []),
            "metadata": dict(record.runtime_metadata or {}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "activated_at": record.activated_at.isoformat() if record.activated_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "error": record.error,
        }

    def _task_record_to_dict(self, record: Any) -> Dict[str, Any]:
        return {
            "id": record.id,
            "mission_id": record.mission_id,
            "tenant_id": record.tenant_id,
            "title": record.title,
            "objective": record.objective,
            "status": record.status,
            "task_type": record.task_type,
            "fleet_id": record.fleet_id,
            "assigned_agent_id": record.assigned_agent_id,
            "parent_task_id": record.parent_task_id,
            "branch_id": record.branch_id,
            "input_payload": dict(record.input_payload or {}),
            "output_payload": dict(record.output_payload or {}),
            "dependencies": list(record.dependencies or []),
            "metadata": dict(record.runtime_metadata or {}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "error": record.error,
        }

    def _branch_record_to_dict(self, record: Any) -> Dict[str, Any]:
        return {
            "id": record.id,
            "mission_id": record.mission_id,
            "tenant_id": record.tenant_id,
            "branch_type": record.branch_type,
            "status": record.status,
            "objective": record.objective,
            "source_task_id": record.source_task_id,
            "source_fleet_id": record.source_fleet_id,
            "parent_branch_id": record.parent_branch_id,
            "spawned_fleet_id": record.spawned_fleet_id,
            "spawned_task_id": record.spawned_task_id,
            "reason": record.reason,
            "metadata": dict(record.runtime_metadata or {}),
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "activated_at": record.activated_at.isoformat() if record.activated_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "error": record.error,
        }
