from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.db.session import DatabaseRuntime


def _sqlite_runtime() -> DatabaseRuntime:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    runtime = DatabaseRuntime.__new__(DatabaseRuntime)
    runtime._engine = engine
    runtime._session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    return runtime


def test_session_scope_commits_and_closes() -> None:
    runtime = _sqlite_runtime()
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    session.execute(text("SELECT 1"))
    with pytest.raises(StopIteration):
        next(generator)


def test_session_scope_rolls_back_on_error() -> None:
    runtime = _sqlite_runtime()
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("boom"))
