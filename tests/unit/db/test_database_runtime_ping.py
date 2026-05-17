from __future__ import annotations

from backend.db.session import DatabaseRuntime


class _Connection:
    def __init__(self, engine: _Engine) -> None:
        self._engine = engine

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._engine.closed = True

    def execute(self, statement) -> None:
        self._engine.executed = str(statement)
        if self._engine.execute_fails:
            raise RuntimeError("postgresql://user:pass@db/name")


class _Engine:
    def __init__(self, *, connect_fails: bool = False, execute_fails: bool = False) -> None:
        self.connect_fails = connect_fails
        self.execute_fails = execute_fails
        self.connects = 0
        self.executed: str | None = None
        self.closed = False

    def connect(self) -> _Connection:
        self.connects += 1
        if self.connect_fails:
            raise RuntimeError("postgresql://user:pass@db/name")
        return _Connection(self)


def _runtime_with_engine(engine: _Engine) -> DatabaseRuntime:
    runtime = DatabaseRuntime.__new__(DatabaseRuntime)
    runtime._engine = engine
    return runtime


def test_database_runtime_ping_executes_non_mutating_select() -> None:
    engine = _Engine()
    runtime = _runtime_with_engine(engine)

    assert runtime.ping() is True
    assert engine.connects == 1
    assert engine.executed == "SELECT 1"
    assert engine.closed is True


def test_database_runtime_ping_returns_false_for_connection_failure() -> None:
    engine = _Engine(connect_fails=True)
    runtime = _runtime_with_engine(engine)

    assert runtime.ping() is False
    assert engine.connects == 1


def test_database_runtime_ping_returns_false_for_query_failure() -> None:
    engine = _Engine(execute_fails=True)
    runtime = _runtime_with_engine(engine)

    assert runtime.ping() is False
    assert engine.connects == 1
    assert engine.closed is True
