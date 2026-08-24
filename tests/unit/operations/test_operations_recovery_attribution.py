from __future__ import annotations

from backend.services.operations_service import OperationsService
from backend.services.runtime_maintainer import RecoverySummary


class _Session:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class _Audit:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:
        self.events.append(event)


class _Maintainer:
    def recover_expired_leases(self) -> RecoverySummary:
        return RecoverySummary(
            expired_lease_count=3,
            requeued_task_count=2,
            dead_lettered_count=1,
            mismatched_state_count=4,
        )


def test_manual_global_recovery_records_human_trigger_identity() -> None:
    service = object.__new__(OperationsService)
    service._session = _Session()
    service._audit = _Audit()
    service._maintainer = _Maintainer()

    summary = service.trigger_recovery(
        actor="user:admin-1",
        actor_tenant_id="admin-home-tenant",
    )

    assert summary.expired_lease_count == 3
    assert [event.action for event in service._audit.events] == [
        "global_recovery_requested",
        "global_recovery_completed",
    ]
    assert all(event.actor == "user:admin-1" for event in service._audit.events)
    assert service._audit.events[0].payload_json["trigger_source"] == "manual_api"
    assert service._audit.events[1].payload_json["mismatched_state_count"] == 4
    assert service._session.commit_count == 2
