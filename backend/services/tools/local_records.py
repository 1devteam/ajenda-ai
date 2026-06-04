from __future__ import annotations

import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.services.tools.schemas import LocalRecord

SUPPORTED_RECORD_TYPES = {"account", "contact", "lead", "opportunity", "activity", "followup_task"}


class LocalRecordProviderError(ValueError):
    """Raised when local record provider access fails closed."""


@dataclass(slots=True)
class LocalRecordProvider:
    """Tenant-scoped local provider used for deterministic runtime action proof."""

    _records: dict[str, dict[str, dict[str, LocalRecord]]] = field(default_factory=lambda: defaultdict(dict))

    def seed(self, *, tenant_id: str, records: list[LocalRecord]) -> None:
        for record in records:
            if record.tenant_id != tenant_id:
                raise LocalRecordProviderError("cannot seed a record into a different tenant")
            self._assert_record_type(record.record_type)
            self._records[tenant_id].setdefault(record.record_type, {})[record.record_id] = record

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[LocalRecord]:
        self._assert_record_type(record_type)
        if limit < 1 or limit > 100:
            raise LocalRecordProviderError("record search limit must be between 1 and 100")
        normalized_query = query.strip().lower()
        filters = filters or {}
        records = list(self._records.get(tenant_id, {}).get(record_type, {}).values())
        matched: list[LocalRecord] = []
        for record in records:
            if (
                normalized_query
                and normalized_query not in record.name.lower()
                and normalized_query not in str(record.fields).lower()
            ):
                continue
            if any(record.fields.get(key) != value for key, value in filters.items()):
                continue
            matched.append(record)
            if len(matched) >= limit:
                break
        return [record.model_copy(deep=True) for record in matched]

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> LocalRecord:
        self._assert_record_type(record_type)
        record = self._records.get(tenant_id, {}).get(record_type, {}).get(record_id)
        if record is None:
            raise LocalRecordProviderError("record not found for tenant")
        return record.model_copy(deep=True)

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        name: str,
        fields: dict[str, Any],
        record_id: str | None = None,
    ) -> LocalRecord:
        self._assert_record_type(record_type)
        normalized_id = record_id or f"local-{uuid.uuid4()}"
        record = LocalRecord(
            tenant_id=tenant_id,
            record_type=record_type,
            record_id=normalized_id,
            name=name,
            fields=deepcopy(fields),
        )
        self._records.setdefault(tenant_id, {}).setdefault(record_type, {})[normalized_id] = record
        return record.model_copy(deep=True)

    def _assert_record_type(self, record_type: str) -> None:
        if record_type not in SUPPORTED_RECORD_TYPES:
            raise LocalRecordProviderError(f"unsupported record type: {record_type}")


_DEFAULT_PROVIDER = LocalRecordProvider()


def default_local_record_provider() -> LocalRecordProvider:
    return _DEFAULT_PROVIDER
