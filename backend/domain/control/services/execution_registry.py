"""
Execution Registry

Lightweight in-memory registry for governed execution objects.

Current incremental stage:
- additive only
- no database persistence yet
- no orchestration migration yet

Purpose:
- provide a single place to register and retrieve runtime execution state
- establish the repository seam before introducing durable persistence
"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.models.domain.execution_branch import ExecutionBranch
from backend.models.domain.execution_task import ExecutionTask
from backend.models.domain.workforce_fleet import WorkforceFleet


class ExecutionRegistry:
    """In-memory registry for fleets, tasks, and branches."""

    def __init__(self) -> None:
        self._fleets: Dict[str, WorkforceFleet] = {}
        self._tasks: Dict[str, ExecutionTask] = {}
        self._branches: Dict[str, ExecutionBranch] = {}

    # Fleet operations
    def register_fleet(self, fleet: WorkforceFleet) -> WorkforceFleet:
        self._fleets[fleet.id] = fleet
        return fleet

    def get_fleet(self, fleet_id: str) -> Optional[WorkforceFleet]:
        return self._fleets.get(fleet_id)

    def list_fleets_for_mission(self, mission_id: str) -> List[WorkforceFleet]:
        return [fleet for fleet in self._fleets.values() if fleet.mission_id == mission_id]

    # Task operations
    def register_task(self, task: ExecutionTask) -> ExecutionTask:
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Optional[ExecutionTask]:
        return self._tasks.get(task_id)

    def list_tasks_for_mission(self, mission_id: str) -> List[ExecutionTask]:
        return [task for task in self._tasks.values() if task.mission_id == mission_id]

    def list_tasks_for_fleet(self, fleet_id: str) -> List[ExecutionTask]:
        return [task for task in self._tasks.values() if task.fleet_id == fleet_id]

    # Branch operations
    def register_branch(self, branch: ExecutionBranch) -> ExecutionBranch:
        self._branches[branch.id] = branch
        return branch

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranch]:
        return self._branches.get(branch_id)

    def list_branches_for_mission(self, mission_id: str) -> List[ExecutionBranch]:
        return [branch for branch in self._branches.values() if branch.mission_id == mission_id]
