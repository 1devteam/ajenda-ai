from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import WorkforceFleetState
from backend.domain.workforce_fleet import WorkforceFleet
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.workforce_fleet_repository import WorkforceFleetRepository
from backend.runtime.transitions import transition_fleet


@dataclass(frozen=True, slots=True)
class FleetResult:
    ok: bool
    fleet_id: uuid.UUID
    state: str


class FleetManager:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._fleets = WorkforceFleetRepository(session)
        self._audit = AuditEventRepository(session)

    def transition(self, *, tenant_id: str, fleet_id: uuid.UUID, target_state: WorkforceFleetState) -> FleetResult:
        fleet = self._require_fleet(fleet_id=fleet_id, tenant_id=tenant_id)
        transition_fleet(fleet, target_state)
        self._session.flush()
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=fleet.mission_id,
                category="fleet",
                action="state_transition",
                actor="fleet_manager",
                details=f"Fleet {fleet.id} moved to {fleet.status}",
                payload_json={"fleet_id": str(fleet.id), "state": fleet.status},
            )
        )
        return FleetResult(True, fleet.id, fleet.status)

    def _require_fleet(self, *, fleet_id: uuid.UUID, tenant_id: str) -> WorkforceFleet:
        fleet = self._fleets.get(fleet_id)
        if fleet is None or fleet.tenant_id != tenant_id:
            raise ValueError("fleet not found for tenant")
        return fleet
