"""Guards for rollback paths that must not mask upstream failures."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.db.session import _safe_rollback


def test_safe_rollback_swallows_dead_connection_errors() -> None:
    session = MagicMock()
    session.rollback.side_effect = RuntimeError("idle-in-transaction timeout")

    _safe_rollback(session)

    session.rollback.assert_called_once()
    session.invalidate.assert_called_once()


def test_safe_rollback_happy_path() -> None:
    session = MagicMock()
    _safe_rollback(session)
    session.rollback.assert_called_once()
    session.invalidate.assert_not_called()
