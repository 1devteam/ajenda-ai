from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.api.routes import branch
from backend.auth.permissions import Permission


def test_branch_creation_requires_mission_manage_permission(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    permission_seen: list[Permission] = []

    def _require_route_permission(*, request, db, permission, tenant_id) -> None:
        permission_seen.append(permission)

    class _BranchManager:
        def __init__(self, db: object) -> None:
            pass

        def create_branch(self, *, tenant_id: str, mission_id: uuid.UUID, parent_branch_id, reason: str):
            return SimpleNamespace(id=uuid.uuid4(), status="open")

    monkeypatch.setattr(branch, "require_route_permission", _require_route_permission)
    monkeypatch.setattr(branch, "BranchManager", _BranchManager)

    request = SimpleNamespace(state=SimpleNamespace(principal=object()))
    body = branch.BranchCreateRequest(
        mission_id=mission_id,
        parent_branch_id=None,
        reason="parallel exploration",
    )

    result = branch.create_branch(body=body, request=request, tenant_id=tenant_id, db=object())

    assert permission_seen == [Permission.MISSION_MANAGE]
    assert result["state"] == "open"


def test_viewer_cannot_create_branch(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    manager = MagicMock()
    monkeypatch.setattr(branch, "BranchManager", lambda _db: manager)
    request = SimpleNamespace(
        state=SimpleNamespace(
            principal=SimpleNamespace(
                subject_id="viewer-user",
                tenant_id=str(tenant_id),
                principal_type="user",
                roles=("viewer",),
                permissions=frozenset(),
            )
        )
    )
    body = branch.BranchCreateRequest(mission_id=uuid.uuid4(), reason="not allowed")

    with pytest.raises(HTTPException) as exc_info:
        branch.create_branch(body=body, request=request, tenant_id=tenant_id, db=MagicMock())

    assert exc_info.value.status_code == 403
    manager.create_branch.assert_not_called()


def test_tenant_admin_can_create_branch(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    created = SimpleNamespace(id=uuid.uuid4(), status="open")
    manager = MagicMock()
    manager.create_branch.return_value = created
    monkeypatch.setattr(branch, "BranchManager", lambda _db: manager)
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
    body = branch.BranchCreateRequest(mission_id=mission_id, reason="authorized")

    result = branch.create_branch(body=body, request=request, tenant_id=tenant_id, db=MagicMock())

    assert result == {"branch_id": str(created.id), "state": "open"}
    manager.create_branch.assert_called_once_with(
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        parent_branch_id=None,
        reason="authorized",
    )
