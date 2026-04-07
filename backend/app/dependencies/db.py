from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from backend.db.session import DatabaseRuntime


def get_database_runtime(request: Request) -> DatabaseRuntime:
    runtime: DatabaseRuntime = request.app.state.database_runtime
    return runtime


def get_db_session(request: Request) -> Generator[Session, None, None]:
    runtime = get_database_runtime(request)
    yield from runtime.session_scope()
