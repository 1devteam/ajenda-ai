from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import Mission, MissionPlan, mission_plan_active_statuses


class MissionPlanRepository:
    """Persistence contract for durable, tenant-owned mission plan records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _active_plan_statement(self, *, mission_id: uuid.UUID, tenant_id: str) -> Select[tuple[MissionPlan]]:
        return (
            select(MissionPlan)
            .where(
                MissionPlan.mission_id == mission_id,
                MissionPlan.tenant_id == tenant_id,
                MissionPlan.status.in_(mission_plan_active_statuses()),
            )
            .order_by(MissionPlan.created_at.asc())
        )

    def get_active_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> MissionPlan | None:
        """Return the active tenant-owned plan for a mission, if one exists."""
        return self._session.scalar(self._active_plan_statement(mission_id=mission_id, tenant_id=tenant_id))

    def get_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> MissionPlan | None:
        """Return the newest tenant-owned plan for a mission, preferring active plans."""
        active_plan = self.get_active_for_mission(mission_id=mission_id, tenant_id=tenant_id)
        if active_plan is not None:
            return active_plan
        stmt = (
            select(MissionPlan)
            .where(MissionPlan.mission_id == mission_id, MissionPlan.tenant_id == tenant_id)
            .order_by(MissionPlan.created_at.desc())
        )
        return self._session.scalar(stmt)

    def create_or_get_active_for_mission(
        self,
        *,
        mission: Mission,
        metadata_json: dict[str, Any],
        status: str = MissionPlanStatus.DRAFT.value,
    ) -> MissionPlan:
        """Create or return the one active plan slot for a tenant-owned mission."""
        allowed_statuses = {value.value for value in MissionPlanStatus}
        if status not in allowed_statuses:
            raise ValueError(f"unknown mission plan status: {status}")
        existing = self.get_active_for_mission(mission_id=mission.id, tenant_id=mission.tenant_id)
        if existing is not None:
            return existing

        plan = MissionPlan(
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            status=status,
            metadata_json=metadata_json,
        )
        self._session.add(plan)
        try:
            self._session.flush()
        except IntegrityError:
            self._session.rollback()
            existing_after_conflict = self.get_active_for_mission(mission_id=mission.id, tenant_id=mission.tenant_id)
            if existing_after_conflict is None:
                raise
            return existing_after_conflict
        self._session.refresh(plan)
        return plan

    def count_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> int:
        """Return the number of tenant-owned plan records for repository contract tests."""
        stmt = select(MissionPlan).where(MissionPlan.mission_id == mission_id, MissionPlan.tenant_id == tenant_id)
        return len(list(self._session.scalars(stmt)))
