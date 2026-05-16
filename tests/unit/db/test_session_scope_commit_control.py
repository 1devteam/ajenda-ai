from __future__ import annotations

import pytest

from backend.db.session import DatabaseRuntime, SKIP_COMMIT_SESSION_INFO_KEY


class _FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, bool] = {}
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _runtime_with_session(session: _FakeSession) -> DatabaseRuntime:
    runtime = DatabaseRuntime.__new__(DatabaseRuntime)
    runtime._session_factory = lambda: session
    return runtime


def test_session_scope_commits_successful_unmarked_session() -> None:
    session = _FakeSession()
    runtime = _runtime_with_session(session)

    with runtime.session_scope():
        pass

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


def test_session_scope_skips_commit_when_readiness_marks_failed_transaction() -> None:
    session = _FakeSession()
    runtime = _runtime_with_session(session)

    with runtime.session_scope() as scoped_session:
        scoped_session.info[SKIP_COMMIT_SESSION_INFO_KEY] = True

    assert session.commits == 0
    assert session.rollbacks == 0
    assert session.closed is True
    assert SKIP_COMMIT_SESSION_INFO_KEY not in session.info


def test_session_scope_still_rolls_back_unhandled_exceptions() -> None:
    session = _FakeSession()
    runtime = _runtime_with_session(session)

    with pytest.raises(RuntimeError, match="boom"):
        with runtime.session_scope():
            raise RuntimeError("boom")

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True
