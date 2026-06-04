from __future__ import annotations

from backend.services.tools.local_calendar import LocalCalendarProvider
from backend.services.tools.local_records import LocalRecordProvider


def test_local_record_provider_is_tenant_scoped_and_resettable() -> None:
    provider = LocalRecordProvider(seed_records={})
    provider.seed_tenant("tenant-a", {"account": {"shared": {"id": "shared", "name": "Tenant A"}}})
    provider.seed_tenant("tenant-b", {"account": {"shared": {"id": "shared", "name": "Tenant B"}}})

    assert provider.read_record(tenant_id="tenant-a", record_type="account", record_id="shared")["name"] == "Tenant A"
    assert provider.read_record(tenant_id="tenant-b", record_type="account", record_id="shared")["name"] == "Tenant B"

    provider.reset({})

    assert provider.search_records(tenant_id="tenant-a", record_type="account", query="Tenant") == []


def test_local_record_provider_search_read_write_and_unsupported_type() -> None:
    provider = LocalRecordProvider(seed_records={})
    written = provider.write_record(
        tenant_id="tenant", record_type="contact", record_id="contact-1", data={"name": "Avery"}
    )

    assert written == {"id": "contact-1", "name": "Avery"}
    assert provider.search_records(tenant_id="tenant", record_type="contact", query="avery") == [written]
    assert provider.read_record(tenant_id="other", record_type="contact", record_id="contact-1") is None

    try:
        provider.search_records(tenant_id="tenant", record_type="secret", query="")
    except ValueError as exc:
        assert "unsupported record_type" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("unsupported record_type should fail")


def test_local_calendar_provider_is_tenant_scoped() -> None:
    provider = LocalCalendarProvider()
    event_a = provider.create_event(tenant_id="tenant-a", calendar_id="primary", event={"title": "A"})
    event_b = provider.create_event(tenant_id="tenant-b", calendar_id="primary", event={"title": "B"})

    assert provider.read_events(tenant_id="tenant-a", calendar_id="primary") == [event_a]
    assert provider.read_events(tenant_id="tenant-b", calendar_id="primary") == [event_b]
