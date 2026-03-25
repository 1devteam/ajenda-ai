"""
Execution Registry

Ephemeral in-memory registry for governed execution objects.

Current transitional role:
- secondary to durable runtime persistence
- used only as a compatibility fallback when repository-backed runtime state
  is unavailable
- not a source of authoritative runtime ownership

Purpose:
- keep live process-local runtime objects accessible during transition
- provide fallback reads while durable runtime ownership is being finalized

Removal target:
- durable repository-backed runtime ownership only

Removal condition:
- all lifecycle reads succeed from durable runtime persistence without
  registry fallback

Removal milestone:
- Exit Transitional Runtime State
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.models.domain.execution_branch import ExecutionBranch
from backend.models.domain.execution_task import ExecutionTask
from backend.models.domain.workforce_fleet import WorkforceFleet


class ExecutionRegistry:
    """Ephemeral compatibility registry for fleets, tasks, and branches."""

    def __init__(self) -> None:
        self._fleets: Dict[str, WorkforceFleet] = {}
        self._tasks: Dict[str, ExecutionTask] = {}
        self._branches: Dict[str, ExecutionBranch] = {}

    def clear(self) -> None:
        """
        Clear all process-local runtime objects.

        Transitional use:
        - tests
        - controlled resets
        - future seam removal validation
        """
        self._fleets.clear()
        self._tasks.clear()
        self._branches.clear()

    # Fleet operations
    def register_fleet(self, fleet: WorkforceFleet) -> WorkforceFleet:
        """Register a process-local fleet compatibility object."""
        self._fleets[fleet.id] = fleet
        return fleet

    def get_fleet(self, fleet_id: str) -> Optional[WorkforceFleet]:
        """Return a process-local fleet fallback object, if present."""
        return self._fleets.get(fleet_id)

    def list_fleets_for_mission(self, mission_id: str) -> List[WorkforceFleet]:
        """List process-local fleet fallback objects for a mission."""
        return [fleet for fleet in self._fleets.values() if fleet.mission_id == mission_id]

    # Task operations
    def register_task(self, task: ExecutionTask) -> ExecutionTask:
        """Register a process-local task compatibility object."""
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Optional[ExecutionTask]:
        """Return a process-local task fallback object, if present."""
        return self._tasks.get(task_id)

    def list_tasks_for_mission(self, mission_id: str) -> List[ExecutionTask]:
        """List process-local task fallback objects for a mission."""
        return [task for task in self._tasks.values() if task.mission_id == mission_id]

    def list_tasks_for_fleet(self, fleet_id: str) -> List[ExecutionTask]:
        """List process-local task fallback objects for a fleet."""
        return [task for task in self._tasks.values() if task.fleet_id == fleet_id]

    # Branch operations
    def register_branch(self, branch: ExecutionBranch) -> ExecutionBranch:
        """Register a process-local branch compatibility object."""
        self._branches[branch.id] = branch
        return branch

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranch]:
        """Return a process-local branch fallback object, if present."""
        return self._branches.get(branch_id)

    def list_branches_for_mission(self, mission_id: str) -> List[ExecutionBranch]:
        """List process-local branch fallback objects for a mission."""
        return [branch for branch in self._branches.values() if branch.mission_id == mission_id]
