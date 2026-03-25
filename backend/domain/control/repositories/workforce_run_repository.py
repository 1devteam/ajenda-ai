"""
Workforce Run Repository

Durable repository for transitional WorkforceRun envelope state.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.database.models import WorkforceRunRecord


class WorkforceRunRepository:
    """Persistence seam for workforce run envelope state."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save_run(self, payload: Dict[str, Any]) -> WorkforceRunRecord:
        run_id = payload["run_id"]
        record = self.db.query(WorkforceRunRecord).filter_by(id=run_id).first()

        if record is None:
            record = WorkforceRunRecord(id=run_id)
            self.db.add(record)

        legacy_sub_missions = list(
            payload.get("legacy_sub_missions", payload.get("sub_missions", []))
        )
        execution_tasks = list(payload.get("execution_tasks", []))
        governed_execution_state = dict(payload.get("governed_execution_state", {}))

        record.workforce_id = payload["workforce_id"]
        record.tenant_id = payload["tenant_id"]
        record.goal = payload["goal"]
        record.status = payload["status"]
        record.pipeline_type = payload.get("pipeline_type", "sequential")
        record.cost = payload.get("cost", 0.0)
        record.final_output = payload.get("final_output")
        record.error = payload.get("error")

        # Transitional compatibility storage:
        # legacy sub-missions are retained only for compatibility.
        # Governed execution_tasks / governed_execution_state are the primary runtime view.
        record.sub_missions = legacy_sub_missions
        record.execution_tasks = execution_tasks
        record.governed_execution_state = governed_execution_state

        record.agents_used = list(payload.get("agents_used", []))
        record.runtime_metadata = dict(payload.get("runtime_metadata", {}))
        record.created_at = payload["created_at"]
        record.started_at = payload.get("started_at")
        record.completed_at = payload.get("completed_at")

        self.db.commit()
        self.db.refresh(record)
        return record

    def get_run(self, run_id: str) -> Optional[WorkforceRunRecord]:
        return self.db.query(WorkforceRunRecord).filter_by(id=run_id).first()
