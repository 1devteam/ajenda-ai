from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from backend.db.tenant_session import activate_tenant_session
from backend.domain.assurance_snapshot import AssuranceSnapshot
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.services.continuous_assurance import ContinuousAssuranceService

pytestmark = pytest.mark.integration


def test_continuous_assurance_persists_tenant_history_without_mutating_mission(pg_session) -> None:
    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())
    pg_session.add(
        Tenant(
            id=uuid.UUID(tenant_id),
            name="Assurance Tenant",
            slug=f"assurance-{tenant_id[:8]}",
            plan="free",
        )
    )
    pg_session.add(
        Tenant(
            id=uuid.UUID(other_tenant_id),
            name="Other Assurance Tenant",
            slug=f"assurance-other-{other_tenant_id[:8]}",
            plan="free",
        )
    )
    pg_session.flush()

    activate_tenant_session(pg_session, tenant_id)
    mission = Mission(
        tenant_id=tenant_id,
        objective="Observe runtime without mutation",
        status="completed",
        metadata_json={"sentinel": "unchanged"},
    )
    pg_session.add(mission)
    pg_session.flush()

    snapshot = ContinuousAssuranceService(pg_session).reconcile_mission(
        tenant_id=tenant_id,
        mission=mission,
    )

    assert snapshot.tenant_id == tenant_id
    assert snapshot.authority_class == "read_model"
    assert snapshot.grants_execution_authority is False
    assert snapshot.status == "incomplete"
    assert snapshot.first_divergence == "mission:execution_tasks"
    assert mission.status == "completed"
    assert mission.metadata_json == {"sentinel": "unchanged"}

    own_rows = list(
        pg_session.scalars(
            select(AssuranceSnapshot).where(AssuranceSnapshot.tenant_id == tenant_id)
        )
    )
    assert [row.id for row in own_rows] == [snapshot.id]

    activate_tenant_session(pg_session, other_tenant_id)
    cross_tenant_rows = list(pg_session.scalars(select(AssuranceSnapshot)))
    assert cross_tenant_rows == []
