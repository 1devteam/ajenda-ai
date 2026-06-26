from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.tools.record_store import LocalRecordStoreAdapter, SessionScopedDurableRecordStore


def test_session_scoped_store_closes_session_per_operation() -> None:
    sessions: list[MagicMock] = []

    def session_factory() -> MagicMock:
        session = MagicMock(name=f"session-{len(sessions)}")
        sessions.append(session)
        return session

    store = SessionScopedDurableRecordStore(session_factory, "tenant-a")

    with (
        patch("backend.services.tools.record_store.activate_tenant_session", return_value=None),
        patch("backend.services.tools.record_store.TenantInternalRecordRepository"),
        patch("backend.services.tools.record_store.DurableRecordStore") as durable_cls,
    ):
        durable = durable_cls.return_value
        durable.search_records.return_value = [{"id": "acct-1"}]
        durable.read_record.return_value = {"id": "acct-1"}
        durable.write_record.return_value = {"id": "acct-1", "name": "Acme"}

        found = store.search_records(tenant_id="tenant-a", record_type="account", query="Acme")
        read = store.read_record(tenant_id="tenant-a", record_type="account", record_id="acct-1")
        written = store.write_record(
            tenant_id="tenant-a",
            record_type="account",
            record_id=None,
            data={"name": "Acme"},
        )

    assert found == [{"id": "acct-1"}]
    assert read == {"id": "acct-1"}
    assert written == {"id": "acct-1", "name": "Acme"}
    assert len(sessions) == 3
    for session in sessions:
        session.commit.assert_called_once()
        session.close.assert_called_once()


def test_resolve_record_store_uses_in_memory_without_session_factory() -> None:
    from backend.services.tools.record_store import resolve_record_store
    from backend.services.tools.schemas import ActionRuntimeContext

    store = resolve_record_store(
        ActionRuntimeContext(
            tenant_id="tenant-a",
            task_id=__import__("uuid").uuid4(),
            worker_id="w",
            lease_id="l",
        )
    )
    assert isinstance(store, LocalRecordStoreAdapter)