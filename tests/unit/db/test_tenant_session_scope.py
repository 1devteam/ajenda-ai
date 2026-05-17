from __future__ import annotations

from typing import Any

import pytest

from backend.db.session import DatabaseRuntime


class _Session:
    def __init__(self) -> None:
        self.executed: list[tuple[Any, dict[str, str]]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement: Any, params: dict[str, str]) -> None:
        self.executed.append((statement, params))

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class _SessionFactory:
    def __init__(self) -> None:
        self.session = _Session()

    def __call__(self) -> _Session:
        return self.session


class _Settings:
    database_url = "sqlite:///:memory:"
    db_pool_size = 5
    db_max_overflow = 10
    db_pool_timeout = 30
    db_pool_recycle = 1800


def _runtime_with_fake_session() -> tuple[DatabaseRuntime, _Session]:
    runtime = DatabaseRuntime(_Settings())  # type: ignore[arg-type]
    factory = _SessionFactory()
    runtime._session_factory = factory
    return runtime, factory.session


def test_tenant_session_scope_sets_postgres_rls_context_and_commits() -> None:
    runtime, session = _runtime_with_fake_session()

    scope = runtime.tenant_session_scope("tenant-a")
    yielded_session = next(scope)
    assert yielded_session is session

    with pytest.raises(StopIteration):
        next(scope)

    assert len(session.executed) == 1
    statement, params = session.executed[0]
    assert "SET LOCAL app.current_tenant_id = :tenant_id" in str(statement)
    assert params == {"tenant_id": "tenant-a"}
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


def test_tenant_session_scope_rolls_back_and_closes_on_error() -> None:
    runtime, session = _runtime_with_fake_session()

    scope = runtime.tenant_session_scope("tenant-a")
    yielded_session = next(scope)
    assert yielded_session is session

    with pytest.raises(RuntimeError, match="boom"):
        scope.throw(RuntimeError("boom"))

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True


def test_tenant_session_scope_rejects_missing_tenant_id() -> None:
    runtime, _session = _runtime_with_fake_session()

    with pytest.raises(ValueError, match="tenant_id is required"):
        next(runtime.tenant_session_scope(""))
