from __future__ import annotations

from unittest.mock import patch

from backend.app.config import Settings
from backend.db.session import DatabaseRuntime


def test_database_runtime_sets_idle_in_transaction_timeout_when_configured() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        db_idle_in_transaction_session_timeout_ms=30_000,
    )

    with patch("backend.db.session.create_engine") as create_engine:
        DatabaseRuntime(settings)

    _, kwargs = create_engine.call_args
    assert kwargs["connect_args"] == {"options": "-c idle_in_transaction_session_timeout=30000"}


def test_database_runtime_omits_connect_args_when_idle_timeout_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_MS", "0")
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        db_idle_in_transaction_session_timeout_ms=0,
    )

    with patch("backend.db.session.create_engine") as create_engine:
        DatabaseRuntime(settings)

    _, kwargs = create_engine.call_args
    assert "connect_args" not in kwargs
