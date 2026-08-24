from __future__ import annotations

from types import SimpleNamespace

from backend.api.routes import operations
from backend.auth.permissions import Permission
from backend.services.runtime_maintainer import RecoverySummary


def test_global_recovery_requires_platform_permission_and_propagates_actor(monkeypatch) -> None:
    permission_seen: list[Permission] = []
    trigger_args: dict[str, str] = {}

    def _require_platform_permission(*, request, db, permission) -> None:
        permission_seen.append(permission)

    class _OperationsService:
        def __init__(self, db: object, queue: object) -> None:
            pass

        def trigger_recovery(self, *, actor: str, actor_tenant_id: str) -> RecoverySummary:
            trigger_args["actor"] = actor
            trigger_args["actor_tenant_id"] = actor_tenant_id
            return RecoverySummary(
                expired_lease_count=2,
                requeued_task_count=1,
                dead_lettered_count=1,
            )

    monkeypatch.setattr(operations, "require_platform_permission", _require_platform_permission)
    monkeypatch.setattr(operations, "OperationsService", _OperationsService)

    request = SimpleNamespace(
        state=SimpleNamespace(
            principal=SimpleNamespace(
                subject_id="user:admin-1",
                tenant_id="admin-home-tenant",
            )
        )
    )

    result = operations.trigger_recovery(request=request, db=object(), queue=object())

    assert permission_seen == [Permission.PLATFORM_OPERATE]
    assert trigger_args == {
        "actor": "user:admin-1",
        "actor_tenant_id": "admin-home-tenant",
    }
    assert result == {
        "expired_lease_count": 2,
        "requeued_task_count": 1,
        "dead_lettered_count": 1,
    }
