from __future__ import annotations

import uuid
from types import SimpleNamespace

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
