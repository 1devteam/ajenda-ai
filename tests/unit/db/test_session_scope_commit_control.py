from __future__ import annotations

import pytest

from backend.db.session import DatabaseRuntime


class _FakeConnection:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails
        self.executes = 0
        self.closed = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def execute(self, *_args: object, **_kwargs: object) -> None:
        self.executes += 1
        if self.fails:
            raise RuntimeError("database failure postgresql://user:pass@db/name")


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.connects = 0

    def connect(self) -> _FakeConnection:
        self.connects += 1
        return self.connection


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _runtime_with_engine(connection: _FakeConnection) -> DatabaseRuntime:
    runtime = DatabaseRuntime.__new__(DatabaseRuntime)
    runtime._engine = _FakeEngine(connection)
    return runtime


def _runtime_with_session(session: _FakeSession) -> DatabaseRuntime:
    runtime = DatabaseRuntime.__new__(DatabaseRuntime)
    runtime._session_factory = lambda: session
    return runtime


def test_database_runtime_ping_returns_true_for_successful_lightweight_query() -> None:
    connection = _FakeConnection()
    runtime = _runtime_with_engine(connection)

    assert runtime.ping() is True
    assert runtime._engine.connects == 1
    assert connection.executes == 1
    assert connection.closed is True


def test_database_runtime_ping_returns_false_for_failed_lightweight_query_without_leaking_exception() -> None:
    connection = _FakeConnection(fails=True)
    runtime = _runtime_with_engine(connection)

    assert runtime.ping() is False
    assert runtime._engine.connects == 1
    assert connection.executes == 1
    assert connection.closed is True


def test_session_scope_keeps_normal_commit_contract() -> None:
    session = _FakeSession()
    runtime = _runtime_with_session(session)

    generator = runtime.session_scope()
    scoped_session = next(generator)
    assert scoped_session is session
    with pytest.raises(StopIteration):
        next(generator)

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


def test_session_scope_still_rolls_back_unhandled_exceptions() -> None:
    session = _FakeSession()
    runtime = _runtime_with_session(session)

    generator = runtime.session_scope()
    scoped_session = next(generator)
    assert scoped_session is session
    with pytest.raises(RuntimeError, match="boom"):
        generator.throw(RuntimeError("boom"))

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True
