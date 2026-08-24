from __future__ import annotations

import uuid
from types import SimpleNamespace

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
