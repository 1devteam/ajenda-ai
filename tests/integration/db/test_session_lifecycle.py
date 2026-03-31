from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.db.session import DatabaseRuntime


class SqliteDatabaseRuntime(DatabaseRuntime):
    @property
    def engine(self):  # type: ignore[override]
        if self._engine is None:
            self._engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        return self._engine


def test_session_scope_commits_and_closes() -> None:
    runtime = SqliteDatabaseRuntime(Settings())
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    session.execute(text("SELECT 1"))
    with pytest.raises(StopIteration):
        next(generator)


def test_session_scope_rolls_back_on_error() -> None:
    runtime = SqliteDatabaseRuntime(Settings())
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("boom"))
