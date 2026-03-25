"""
Fleet Manager

Lightweight control-layer seam for governed fleet lifecycle management.

Current incremental stage:
- additive only
- no persistence layer yet
- no runtime orchestration migration yet
- used to centralize fleet creation / annotation rules
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from backend.models.domain.workforce_fleet import (
    WorkforceFleet,
    WorkforceFleetStatus,
    WorkforceFleetType,
)


class FleetManager:
    """
    Governs fleet lifecycle metadata.

    This service exists as the first explicit separation point between:
    - provisioning mechanics
    - future runtime fleet management
    """

    def create_fleet(
        self,
        *,
        mission_id: str,
        tenant_id: str,
        objective: str,
        fleet_type: WorkforceFleetType = WorkforceFleetType.SINGLE,
        primary_agent_id: Optional[str] = None,
        agent_ids: Optional[list[str]] = None,
        branch_id: Optional[str] = None,
        parent_fleet_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkforceFleet:
        metadata = metadata or {}
        agent_ids = list(agent_ids or [])

        if primary_agent_id and primary_agent_id not in agent_ids:
            agent_ids.insert(0, primary_agent_id)

        return WorkforceFleet(
            id=self._new_fleet_id(),
            mission_id=mission_id,
            tenant_id=tenant_id,
            status=WorkforceFleetStatus.READY,
            fleet_type=fleet_type,
            objective=objective,
            primary_agent_id=primary_agent_id,
            agent_ids=agent_ids,
            branch_id=branch_id,
            parent_fleet_id=parent_fleet_id,
            metadata={
                **metadata,
                "created_by": "fleet_manager",
                "created_at": datetime.utcnow().isoformat(),
            },
        )

    def activate_fleet(self, fleet: WorkforceFleet) -> WorkforceFleet:
        fleet.status = WorkforceFleetStatus.ACTIVE
        fleet.activated_at = datetime.utcnow()
        return fleet

    def complete_fleet(self, fleet: WorkforceFleet) -> WorkforceFleet:
        fleet.status = WorkforceFleetStatus.COMPLETED
        fleet.completed_at = datetime.utcnow()
        return fleet

    def fail_fleet(self, fleet: WorkforceFleet, error: str) -> WorkforceFleet:
        fleet.status = WorkforceFleetStatus.FAILED
        fleet.error = error
        fleet.completed_at = datetime.utcnow()
        return fleet

    def _new_fleet_id(self) -> str:
        return f"fleet_{uuid4().hex}"
