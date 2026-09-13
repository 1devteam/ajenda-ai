from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission


class MissionRepository:
    """Persistence contract for canonical mission records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, mission: Mission) -> Mission:
        self._session.add(mission)
        self._session.flush()
        self._session.refresh(mission)
        return mission

    def get(self, mission_id: uuid.UUID) -> Mission | None:
        return self._session.get(Mission, mission_id)

    def update_metadata(self, *, mission: Mission, metadata_json: dict[str, Any]) -> Mission:
        mission.metadata_json = metadata_json
        self._session.add(mission)
        self._session.flush()
        self._session.refresh(mission)
        return mission

    def get_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        stmt = select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def lock_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        """Return a tenant-owned mission while holding a row lock for mutation serialization."""
        stmt = select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id).with_for_update()
        return self._session.scalar(stmt)

    def list_by_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Mission]:
        stmt = (
            select(Mission)
            .where(Mission.tenant_id == tenant_id)
            .order_by(Mission.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        missions = list(self._session.scalars(stmt))
        self._reconcile_review_holds(missions=missions, tenant_id=tenant_id)
        return missions

    def _reconcile_review_holds(self, *, missions: list[Mission], tenant_id: str) -> None:
        """Pause running missions that have no executable tasks left.

        A mission waiting only on human review is not actively running. Keep the
        mission and task history intact, but make that state explicit so active
        work stays readable and operators can find the review queue separately.
        """

        running = [mission for mission in missions if mission.status == MissionState.RUNNING.value]
        if not running:
            return
        counts = self._session.execute(
            select(
                ExecutionTask.mission_id,
                ExecutionTask.status,
                func.count().label("count"),
            )
            .where(
                ExecutionTask.tenant_id == tenant_id,
                ExecutionTask.mission_id.in_([mission.id for mission in running]),
            )
            .group_by(ExecutionTask.mission_id, ExecutionTask.status)
        ).all()
        by_mission: dict[uuid.UUID, dict[str, int]] = {}
        for mission_id, status, count in counts:
            by_mission.setdefault(mission_id, {})[str(status)] = int(count)
        active_states = {
            ExecutionTaskState.PLANNED.value,
            ExecutionTaskState.QUEUED.value,
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.RECOVERING.value,
        }
        for mission in running:
            state_counts = by_mission.get(mission.id, {})
            pending_review = state_counts.get(ExecutionTaskState.PENDING_REVIEW.value, 0)
            active = sum(state_counts.get(state, 0) for state in active_states)
            if pending_review <= 0 or active > 0:
                continue
            metadata = dict(mission.metadata_json or {})
            metadata["runtime_reconciliation"] = {
                "schema_version": 1,
                "reason": "review_hold_without_active_tasks",
                "previous_status": MissionState.RUNNING.value,
                "pending_review_task_count": pending_review,
                "reconciled_at": datetime.now(UTC).isoformat(),
            }
            mission.status = MissionState.PAUSED.value
            mission.metadata_json = metadata
            self._session.add(mission)
        self._session.flush()
