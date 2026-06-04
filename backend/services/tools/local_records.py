from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_RECORD_TYPES = {"account", "contact", "opportunity", "activity", "task"}

_DEFAULT_FIXTURES: dict[str, dict[str, dict[str, dict[str, Any]]]] = {
    "default": {
        "account": {
            "acct-1": {"id": "acct-1", "name": "Acme Manufacturing", "industry": "manufacturing", "score": 84},
            "acct-2": {"id": "acct-2", "name": "Northwind Labs", "industry": "software", "score": 71},
        },
        "contact": {
            "cont-1": {"id": "cont-1", "name": "Avery Stone", "account_id": "acct-1", "role": "VP Operations"},
            "cont-2": {"id": "cont-2", "name": "Jordan Lee", "account_id": "acct-2", "role": "Director"},
        },
        "opportunity": {
            "opp-1": {"id": "opp-1", "name": "Acme Expansion", "account_id": "acct-1", "stage": "qualified"}
        },
        "activity": {},
        "task": {},
    }
}


@dataclass(slots=True)
class LocalRecordProvider:
    """Tenant-scoped deterministic proof provider, not durable CRM storage."""

    seed_records: dict[str, dict[str, dict[str, dict[str, Any]]]] | None = None
    _records: dict[str, dict[str, dict[str, dict[str, Any]]]] = field(init=False, repr=False)
    _default_tenant_template: dict[str, dict[str, dict[str, Any]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.reset(self.seed_records)

    def reset(self, seed_records: dict[str, dict[str, dict[str, dict[str, Any]]]] | None = None) -> None:
        self._records = deepcopy(seed_records if seed_records is not None else _DEFAULT_FIXTURES)
        self._default_tenant_template = deepcopy(_DEFAULT_FIXTURES["default"] if seed_records is None else {})

    def seed_tenant(self, tenant_id: str, records: dict[str, dict[str, dict[str, Any]]]) -> None:
        normalized: dict[str, dict[str, dict[str, Any]]] = {record_type: {} for record_type in SUPPORTED_RECORD_TYPES}
        for record_type, values in records.items():
            self._validate_record_type(record_type)
            normalized[record_type] = deepcopy(values)
        self._records[tenant_id] = normalized

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._validate_record_type(record_type)
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        source = self._tenant_records(tenant_id).get(record_type, {})
        filters = filters or {}
        normalized_query = query.lower().strip()
        matches: list[dict[str, Any]] = []
        for record in source.values():
            if normalized_query and normalized_query not in " ".join(str(value).lower() for value in record.values()):
                continue
            if any(record.get(key) != value for key, value in filters.items()):
                continue
            matches.append(deepcopy(record))
            if len(matches) >= limit:
                break
        return matches

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        self._validate_record_type(record_type)
        record = self._tenant_records(tenant_id).get(record_type, {}).get(record_id)
        return deepcopy(record) if record is not None else None

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_record_type(record_type)
        tenant_records = self._tenant_records(tenant_id)
        record_bucket = tenant_records.setdefault(record_type, {})
        final_id = record_id or f"{record_type}-{len(record_bucket) + 1}"
        record = {"id": final_id, **deepcopy(data)}
        record_bucket[final_id] = record
        return deepcopy(record)

    def _tenant_records(self, tenant_id: str) -> dict[str, dict[str, dict[str, Any]]]:
        if tenant_id not in self._records:
            self._records[tenant_id] = deepcopy(self._default_tenant_template)
        return self._records[tenant_id]

    @staticmethod
    def _validate_record_type(record_type: str) -> None:
        if record_type not in SUPPORTED_RECORD_TYPES:
            raise ValueError(f"unsupported record_type: {record_type}")


_DEFAULT_LOCAL_RECORD_PROVIDER = LocalRecordProvider()


def default_local_record_provider() -> LocalRecordProvider:
    return _DEFAULT_LOCAL_RECORD_PROVIDER


def reset_default_local_record_provider(
    seed_records: dict[str, dict[str, dict[str, dict[str, Any]]]] | None = None,
) -> None:
    _DEFAULT_LOCAL_RECORD_PROVIDER.reset(seed_records)


def build_local_record_provider(
    seed_records: dict[str, dict[str, dict[str, dict[str, Any]]]] | None = None,
) -> LocalRecordProvider:
    return LocalRecordProvider(seed_records=seed_records)
