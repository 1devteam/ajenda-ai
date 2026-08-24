from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes import workforce
from backend.auth.permissions import Permission


def test_foreign_mission_is_rejected_before_quota_consumption(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    permission_seen: list[Permission] = []
    quota_called = False

    def _require_route_permission(*, request, db, permission, tenant_id) -> None:
        permission_seen.append(permission)

    class _MissionRepository:
        def __init__(self, session: object) -> None:
            pass

        def get_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str):
            return None

    class _QuotaService:
        def __init__(self, session: object) -> None:
            pass

        def check_and_record_agent_provisioning(self, tenant_id, *, agents_requested: int) -> None:
            nonlocal quota_called
            quota_called = True

    monkeypatch.setattr(workforce, "require_route_permission", _require_route_permission)
    monkeypatch.setattr(workforce, "MissionRepository", _MissionRepository)
    monkeypatch.setattr(workforce, "QuotaEnforcementService", _QuotaService)

    body = workforce.ProvisionFleetRequest(
        mission_id=str(uuid.uuid4()),
        fleet_name="test fleet",
        agents=[],
    )
    request = SimpleNamespace(state=SimpleNamespace(principal=object()))

    with pytest.raises(HTTPException) as exc_info:
        workforce.provision_workforce(body=body, request=request, tenant_id=tenant_id, db=object())

    assert exc_info.value.status_code == 400
    assert permission_seen == [Permission.PROVISION_WORKFORCE]
    assert quota_called is False


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_principal_without_workforce_permission_cannot_provision(monkeypatch, role: str) -> None:
    tenant_id = uuid.uuid4()
    mission_repository = MagicMock()
    quota = MagicMock()
    provisioner = MagicMock()
    monkeypatch.setattr(workforce, "MissionRepository", lambda _db: mission_repository)
    monkeypatch.setattr(workforce, "QuotaEnforcementService", lambda _db: quota)
    monkeypatch.setattr(workforce, "WorkforceProvisioner", lambda _db: provisioner)
    request = SimpleNamespace(
        state=SimpleNamespace(
            principal=SimpleNamespace(
                subject_id=f"{role}-user",
                tenant_id=str(tenant_id),
                principal_type="user",
                roles=(role,),
                permissions=frozenset(),
            )
        )
    )
    body = workforce.ProvisionFleetRequest(
        mission_id=str(uuid.uuid4()),
        fleet_name="forbidden fleet",
        agents=[],
    )

    with pytest.raises(HTTPException) as exc_info:
        workforce.provision_workforce(body=body, request=request, tenant_id=tenant_id, db=MagicMock())

    assert exc_info.value.status_code == 403
    mission_repository.get_for_tenant.assert_not_called()
    quota.check_and_record_agent_provisioning.assert_not_called()
    provisioner.provision_fleet.assert_not_called()


def test_tenant_admin_can_provision_workforce(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    mission_repository = MagicMock()
    mission_repository.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    quota = MagicMock()
    provisioner = MagicMock()
    fleet = SimpleNamespace(id=uuid.uuid4(), status="ready")
    provisioner.provision_fleet.return_value = fleet
    monkeypatch.setattr(workforce, "MissionRepository", lambda _db: mission_repository)
    monkeypatch.setattr(workforce, "QuotaEnforcementService", lambda _db: quota)
    monkeypatch.setattr(workforce, "WorkforceProvisioner", lambda _db: provisioner)
    request = SimpleNamespace(
        state=SimpleNamespace(
            principal=SimpleNamespace(
                subject_id="tenant-admin-user",
                tenant_id=str(tenant_id),
                principal_type="user",
                roles=("tenant_admin",),
                permissions=frozenset(),
            )
        )
    )
    body = workforce.ProvisionFleetRequest(
        mission_id=str(mission_id),
        fleet_name="authorized fleet",
        agents=[workforce.AgentSpec(display_name="Agent", role_name="operator")],
    )

    result = workforce.provision_workforce(body=body, request=request, tenant_id=tenant_id, db=MagicMock())

    assert result == {"fleet_id": str(fleet.id), "state": "ready"}
    mission_repository.get_for_tenant.assert_called_once_with(
        mission_id=mission_id,
        tenant_id=str(tenant_id),
    )
    quota.check_and_record_agent_provisioning.assert_called_once_with(tenant_id, agents_requested=1)
    provisioner.provision_fleet.assert_called_once_with(
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        fleet_name="authorized fleet",
        agent_specs=[("Agent", "operator")],
    )
