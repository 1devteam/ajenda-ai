"""
Execution Runtime Repository

Durable repository for governed runtime execution objects.

Current incremental stage:
- additive only
- direct SQLAlchemy persistence for fleets, tasks, and branches
- no orchestration migration yet
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from backend.database.models import (
    ExecutionBranchRecord,
    ExecutionTaskRecord,
    WorkforceFleetRecord,
)
from backend.models.domain.execution_branch import ExecutionBranch
from backend.models.domain.execution_task import ExecutionTask
from backend.models.domain.workforce_fleet import WorkforceFleet


class ExecutionRuntimeRepository:
    """Persistence seam for governed runtime execution objects."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -------------------------------------------------------------------------
    # Fleet persistence
    # -------------------------------------------------------------------------

    def save_fleet(self, fleet: WorkforceFleet) -> WorkforceFleetRecord:
        record = self.db.query(WorkforceFleetRecord).filter_by(id=fleet.id).first()

        if record is None:
            record = WorkforceFleetRecord(id=fleet.id)
            self.db.add(record)

        record.mission_id = fleet.mission_id
        record.tenant_id = fleet.tenant_id
        record.status = str(fleet.status)
        record.fleet_type = str(fleet.fleet_type)
        record.objective = fleet.objective
        record.primary_agent_id = fleet.primary_agent_id
        record.branch_id = fleet.branch_id
        record.parent_fleet_id = fleet.parent_fleet_id
        record.agent_ids = list(fleet.agent_ids)
        record.runtime_metadata = dict(fleet.metadata)
        record.created_at = fleet.created_at
        record.activated_at = fleet.activated_at
        record.completed_at = fleet.completed_at
        record.error = fleet.error

        self.db.commit()
        self.db.refresh(record)
        return record

    def get_fleet(self, fleet_id: str) -> Optional[WorkforceFleetRecord]:
        return self.db.query(WorkforceFleetRecord).filter_by(id=fleet_id).first()

    def list_fleets_for_mission(self, mission_id: str) -> List[WorkforceFleetRecord]:
        return (
            self.db.query(WorkforceFleetRecord)
            .filter_by(mission_id=mission_id)
            .order_by(WorkforceFleetRecord.created_at.asc(), WorkforceFleetRecord.id.asc())
            .all()
        )

    # -------------------------------------------------------------------------
    # Task persistence
    # -------------------------------------------------------------------------

    def save_task(self, task: ExecutionTask) -> ExecutionTaskRecord:
        record = self.db.query(ExecutionTaskRecord).filter_by(id=task.id).first()

        if record is None:
            record = ExecutionTaskRecord(id=task.id)
            self.db.add(record)

        record.mission_id = task.mission_id
        record.tenant_id = task.tenant_id
        record.title = task.title
        record.objective = task.objective
        record.status = str(task.status)
        record.task_type = str(task.task_type)
        record.fleet_id = task.fleet_id
        record.assigned_agent_id = task.assigned_agent_id
        record.parent_task_id = task.parent_task_id
        record.branch_id = task.branch_id
        record.input_payload = dict(task.input_payload)
        record.output_payload = dict(task.output_payload)
        record.dependencies = list(task.dependencies)
        record.runtime_metadata = dict(task.metadata)
        record.created_at = task.created_at
        record.started_at = task.started_at
        record.completed_at = task.completed_at
        record.error = task.error

        self.db.commit()
        self.db.refresh(record)
        return record

    def get_task(self, task_id: str) -> Optional[ExecutionTaskRecord]:
        return self.db.query(ExecutionTaskRecord).filter_by(id=task_id).first()

    def list_tasks_for_mission(self, mission_id: str) -> List[ExecutionTaskRecord]:
        return (
            self.db.query(ExecutionTaskRecord)
            .filter_by(mission_id=mission_id)
            .order_by(ExecutionTaskRecord.created_at.asc(), ExecutionTaskRecord.id.asc())
            .all()
        )

    def list_tasks_for_fleet(self, fleet_id: str) -> List[ExecutionTaskRecord]:
        return (
            self.db.query(ExecutionTaskRecord)
            .filter_by(fleet_id=fleet_id)
            .order_by(ExecutionTaskRecord.created_at.asc(), ExecutionTaskRecord.id.asc())
            .all()
        )

    # -------------------------------------------------------------------------
    # Branch persistence
    # -------------------------------------------------------------------------

    def save_branch(self, branch: ExecutionBranch) -> ExecutionBranchRecord:
        record = self.db.query(ExecutionBranchRecord).filter_by(id=branch.id).first()

        if record is None:
            record = ExecutionBranchRecord(id=branch.id)
            self.db.add(record)

        record.mission_id = branch.mission_id
        record.tenant_id = branch.tenant_id
        record.branch_type = str(branch.branch_type)
        record.status = str(branch.status)
        record.objective = branch.objective
        record.source_task_id = branch.source_task_id
        record.source_fleet_id = branch.source_fleet_id
        record.parent_branch_id = branch.parent_branch_id
        record.spawned_fleet_id = branch.spawned_fleet_id
        record.spawned_task_id = branch.spawned_task_id
        record.reason = branch.reason
        record.runtime_metadata = dict(branch.metadata)
        record.created_at = branch.created_at
        record.activated_at = branch.activated_at
        record.completed_at = branch.completed_at
        record.error = branch.error

        self.db.commit()
        self.db.refresh(record)
        return record

    def get_branch(self, branch_id: str) -> Optional[ExecutionBranchRecord]:
        return self.db.query(ExecutionBranchRecord).filter_by(id=branch_id).first()

    def list_branches_for_mission(self, mission_id: str) -> List[ExecutionBranchRecord]:
        return (
            self.db.query(ExecutionBranchRecord)
            .filter_by(mission_id=mission_id)
            .order_by(ExecutionBranchRecord.created_at.asc(), ExecutionBranchRecord.id.asc())
            .all()
        )
