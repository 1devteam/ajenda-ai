from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.mission import Mission
from backend.repositories.mission_repository import MissionRepository


def test_get_for_tenant_uses_tenant_scoped_query() -> None:
    mission_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    mission = Mission(tenant_id=tenant_id, objective="Tenant-scoped mission", metadata_json={})
    session = MagicMock()
    session.scalar.return_value = mission

    result = MissionRepository(session).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id)

    assert result is mission
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "missions.id" in compiled
    assert "missions.tenant_id" in compiled
    assert tenant_id in compiled


def test_update_metadata_flushes_and_refreshes_existing_mission() -> None:
    mission = Mission(tenant_id="tenant-a", objective="Tenant-scoped mission", metadata_json={})
    session = MagicMock()

    result = MissionRepository(session).update_metadata(
        mission=mission,
        metadata_json={"mission_plan": {"schema_version": 1, "planning_status": "draft"}},
    )

    assert result is mission
    assert mission.metadata_json == {"mission_plan": {"schema_version": 1, "planning_status": "draft"}}
    session.add.assert_called_once_with(mission)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(mission)
