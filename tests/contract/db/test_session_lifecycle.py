from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.db.session import DatabaseRuntime


def _sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> DatabaseRuntime:
    monkeypatch.setenv("AJENDA_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    get_settings.cache_clear()
    return DatabaseRuntime(get_settings())


def test_session_scope_commits_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _sqlite_runtime(monkeypatch)
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    session.execute(text("SELECT 1"))
    with pytest.raises(StopIteration):
        next(generator)


def test_session_scope_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _sqlite_runtime(monkeypatch)
    generator = runtime.session_scope()
    session = next(generator)
    assert isinstance(session, Session)
    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("boom"))
