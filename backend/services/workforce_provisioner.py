from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.enums import UserWorkforceAgentState, WorkforceFleetState
from backend.domain.lineage_record import LineageRecord
from backend.domain.user_workforce_agent import UserWorkforceAgent
from backend.domain.workforce_fleet import WorkforceFleet
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.lineage_record_repository import LineageRecordRepository
from backend.repositories.user_workforce_agent_repository import UserWorkforceAgentRepository
from backend.repositories.workforce_fleet_repository import WorkforceFleetRepository
from backend.runtime.transitions import transition_agent, transition_fleet


class WorkforceProvisioner:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._fleets = WorkforceFleetRepository(session)
        self._agents = UserWorkforceAgentRepository(session)
        self._audit = AuditEventRepository(session)
        self._lineage = LineageRecordRepository(session)

    def provision_fleet(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        fleet_name: str,
        agent_specs: list[tuple[str, str]],
    ) -> WorkforceFleet:
        fleet = self._fleets.add(
            WorkforceFleet(
                tenant_id=tenant_id,
                mission_id=mission_id,
                name=fleet_name,
                status=WorkforceFleetState.PLANNED.value,
            )
        )
        transition_fleet(fleet, WorkforceFleetState.PROVISIONING)
        self._session.flush()
        for display_name, role_name in agent_specs:
            agent = self._agents.add(
                UserWorkforceAgent(
                    tenant_id=tenant_id,
                    mission_id=mission_id,
                    fleet_id=fleet.id,
                    display_name=display_name,
                    role_name=role_name,
                    status=UserWorkforceAgentState.PLANNED.value,
                )
            )
            transition_agent(agent, UserWorkforceAgentState.PROVISIONED)
            self._lineage.append(
                LineageRecord(
                    tenant_id=tenant_id,
                    mission_id=mission_id,
                    fleet_id=fleet.id,
                    relationship_type="fleet_agent_membership",
                    relationship_reason="spawn boundary",
                    metadata_json={"agent_id": str(agent.id), "role_name": role_name},
                )
            )
        transition_fleet(fleet, WorkforceFleetState.READY)
        self._session.flush()
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                mission_id=mission_id,
                category="provisioning",
                action="fleet_provisioned",
                actor="workforce_provisioner",
                details=f"Provisioned fleet {fleet.id}",
                payload_json={"fleet_id": str(fleet.id), "agent_count": len(agent_specs)},
            )
        )
        return fleet
