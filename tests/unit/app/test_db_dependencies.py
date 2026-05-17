from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


class _Runtime:
    def __init__(self) -> None:
        self.tenant_id: str | None = None

    def tenant_session_scope(self, tenant_id: str) -> Any:
        self.tenant_id = tenant_id
        yield "tenant-session"


def _request(*, tenant_id: str | None) -> SimpleNamespace:
    runtime = _Runtime()
    return SimpleNamespace(
        state=SimpleNamespace(tenant_id=tenant_id),
        app=SimpleNamespace(state=SimpleNamespace(database_runtime=runtime)),
    )


def test_get_request_tenant_id_reads_request_state() -> None:
    request = _request(tenant_id="tenant-a")

    assert get_request_tenant_id(request) == "tenant-a"  # type: ignore[arg-type]


def test_get_request_tenant_id_rejects_missing_context() -> None:
    request = _request(tenant_id=None)

    with pytest.raises(HTTPException) as exc_info:
        get_request_tenant_id(request)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 400


def test_get_tenant_db_session_uses_tenant_session_scope() -> None:
    request = _request(tenant_id="tenant-a")
    dependency = get_tenant_db_session(request)  # type: ignore[arg-type]

    assert next(dependency) == "tenant-session"

    with pytest.raises(StopIteration):
        next(dependency)

    assert request.app.state.database_runtime.tenant_id == "tenant-a"
