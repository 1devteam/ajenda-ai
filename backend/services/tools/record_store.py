from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

from sqlalchemy.orm import Session

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.tools.local_records import LocalRecordProvider, default_local_record_provider
from backend.services.tools.schemas import ActionRuntimeContext

_T = TypeVar("_T")


@runtime_checkable
class RecordStore(Protocol):
    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None: ...

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]: ...


class DurableRecordStore:
    """Tenant-scoped durable record store backed by Postgres."""

    def __init__(self, repository: TenantInternalRecordRepository) -> None:
        self._repo = repository

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._repo.seed_defaults_if_empty(tenant_id=tenant_id)
        return self._repo.search_records(
            tenant_id=tenant_id,
            record_type=record_type,
            query=query,
            filters=filters,
            limit=limit,
        )

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        self._repo.seed_defaults_if_empty(tenant_id=tenant_id)
        return self._repo.read_record(tenant_id=tenant_id, record_type=record_type, record_id=record_id)

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._repo.write_record(
            tenant_id=tenant_id,
            record_type=record_type,
            record_id=record_id,
            data=data,
        )


class SessionScopedDurableRecordStore:
    """Durable store that opens/closes a tenant DB session per operation.

    Prevents connection-pool exhaustion when handlers call resolve_record_store()
    multiple times in one tool.invoke execution (e.g. web.research, sales.research).
    """

    def __init__(self, session_factory: Callable[[], Session], tenant_id: str) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id

    def _with_store(self, operation: Callable[[DurableRecordStore], _T]) -> _T:
        session = self._session_factory()
        try:
            activate_tenant_session(session, self._tenant_id)
            result = operation(DurableRecordStore(TenantInternalRecordRepository(session)))
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._with_store(
            lambda store: store.search_records(
                tenant_id=tenant_id,
                record_type=record_type,
                query=query,
                filters=filters,
                limit=limit,
            )
        )

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        return self._with_store(
            lambda store: store.read_record(
                tenant_id=tenant_id,
                record_type=record_type,
                record_id=record_id,
            )
        )

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._with_store(
            lambda store: store.write_record(
                tenant_id=tenant_id,
                record_type=record_type,
                record_id=record_id,
                data=data,
            )
        )


class LocalRecordStoreAdapter:
    """Adapter wrapping the in-memory LocalRecordProvider."""

    def __init__(self, provider: LocalRecordProvider | None = None) -> None:
        self._provider = provider or default_local_record_provider()

    def search_records(
        self,
        *,
        tenant_id: str,
        record_type: str,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._provider.search_records(
            tenant_id=tenant_id,
            record_type=record_type,
            query=query,
            filters=filters,
            limit=limit,
        )

    def read_record(self, *, tenant_id: str, record_type: str, record_id: str) -> dict[str, Any] | None:
        return self._provider.read_record(tenant_id=tenant_id, record_type=record_type, record_id=record_id)

    def write_record(
        self,
        *,
        tenant_id: str,
        record_type: str,
        record_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._provider.write_record(
            tenant_id=tenant_id,
            record_type=record_type,
            record_id=record_id,
            data=data,
        )


def _session_factory_supports_durable_store(session_factory: Callable[[], Session]) -> bool:
    session = session_factory()
    try:
        return all(hasattr(session, attr) for attr in ("execute", "commit", "rollback", "close"))
    finally:
        session.close()


def resolve_record_store(context: ActionRuntimeContext) -> RecordStore:
    session_factory = context.session_factory
    if session_factory is None or not _session_factory_supports_durable_store(session_factory):
        return LocalRecordStoreAdapter()
    return SessionScopedDurableRecordStore(session_factory, context.tenant_id)


def record_store_limitations(context: ActionRuntimeContext) -> list[str]:
    if context.session_factory is None:
        return ["in-memory proof provider; records reset on process restart"]
    return ["durable tenant-scoped internal records (Ajenda central brain)"]