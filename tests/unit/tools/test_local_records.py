from __future__ import annotations

import pytest

from backend.services.tools.local_records import LocalRecordProvider, LocalRecordProviderError
from backend.services.tools.schemas import LocalRecord


def _provider() -> LocalRecordProvider:
    provider = LocalRecordProvider()
    provider.seed(
        tenant_id="tenant-a",
        records=[
            LocalRecord(
                tenant_id="tenant-a",
                record_type="lead",
                record_id="lead-1",
                name="Acme Lead",
                fields={"industry": "software", "budget": 20000},
            )
        ],
    )
    provider.seed(
        tenant_id="tenant-b",
        records=[
            LocalRecord(
                tenant_id="tenant-b",
                record_type="lead",
                record_id="lead-1",
                name="Foreign Lead",
                fields={"industry": "finance"},
            )
        ],
    )
    return provider


def test_search_records_is_tenant_scoped() -> None:
    results = _provider().search_records(tenant_id="tenant-a", record_type="lead", query="acme")

    assert [record.name for record in results] == ["Acme Lead"]


def test_read_record_rejects_cross_tenant_access_by_not_found() -> None:
    record = _provider().read_record(tenant_id="tenant-b", record_type="lead", record_id="lead-1")

    assert record.name == "Foreign Lead"
    assert record.tenant_id == "tenant-b"


def test_search_records_rejects_unsupported_record_type() -> None:
    with pytest.raises(LocalRecordProviderError, match="unsupported record type"):
        _provider().search_records(tenant_id="tenant-a", record_type="invoice")


def test_write_record_persists_to_tenant_scope() -> None:
    provider = _provider()
    created = provider.write_record(
        tenant_id="tenant-a",
        record_type="activity",
        name="Called lead",
        fields={"record_id": "lead-1"},
    )

    read = provider.read_record(tenant_id="tenant-a", record_type="activity", record_id=created.record_id)
    assert read.name == "Called lead"
    assert read.fields == {"record_id": "lead-1"}
