from __future__ import annotations

import uuid
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import capability as capability_module
from backend.api.routes import capability_adapter as adapter_module
from backend.api.routes import evidence as evidence_module
from backend.api.routes import outcome_review as outcome_review_module
from backend.api.routes import retrieval_contract as retrieval_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from tests.unit.api.test_capability_adapter_route import _valid_payload as _adapter_payload
from tests.unit.api.test_capability_registry_route import _valid_payload as _capability_payload
from tests.unit.api.test_evidence_route import _valid_payload as _evidence_payload
from tests.unit.api.test_outcome_review_route import _valid_payload as _outcome_payload
from tests.unit.api.test_retrieval_contract_route import _valid_payload as _retrieval_payload


def _build_client(*, tenant_id: uuid.UUID, roles: tuple[str, ...] = ("viewer",)) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-viewer",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=roles,
        )
        return await call_next(request)

    app.include_router(capability_module.router, prefix="/v1")
    app.include_router(adapter_module.router, prefix="/v1")
    app.include_router(evidence_module.router, prefix="/v1")
    app.include_router(outcome_review_module.router, prefix="/v1")
    app.include_router(retrieval_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return TestClient(app, raise_server_exceptions=False)


RouteCall = tuple[str, str, Callable[[uuid.UUID], dict[str, object]]]


def _capability_patch(_: uuid.UUID) -> dict[str, object]:
    return {"enabled": False}


def _adapter_patch(_: uuid.UUID) -> dict[str, object]:
    return {"enabled": False}


def _evidence_create(mission_id: uuid.UUID) -> dict[str, object]:
    return _evidence_payload(mission_id=mission_id)


def _evidence_patch(_: uuid.UUID) -> dict[str, object]:
    return {"collection_status": "verified"}


def _outcome_create(mission_id: uuid.UUID) -> dict[str, object]:
    return _outcome_payload(mission_id=mission_id)


def _outcome_patch(_: uuid.UUID) -> dict[str, object]:
    return {"review_status": "completed", "confidence": 0.95}


def _retrieval_create(mission_id: uuid.UUID) -> dict[str, object]:
    return _retrieval_payload(mission_id=mission_id)


def _retrieval_patch(_: uuid.UUID) -> dict[str, object]:
    return {"retrieval_status": "fulfilled"}


@pytest.mark.parametrize(
    ("method", "path", "payload_factory"),
    [
        ("post", "/v1/capabilities", lambda _mission_id: _capability_payload()),
        ("patch", f"/v1/capabilities/{uuid.uuid4()}", _capability_patch),
        ("post", "/v1/capability-adapters", lambda _mission_id: _adapter_payload()),
        ("patch", f"/v1/capability-adapters/{uuid.uuid4()}", _adapter_patch),
        ("post", "/v1/evidence", _evidence_create),
        ("patch", f"/v1/evidence/{uuid.uuid4()}", _evidence_patch),
        ("post", "/v1/outcome-reviews", _outcome_create),
        ("patch", f"/v1/outcome-reviews/{uuid.uuid4()}", _outcome_patch),
        ("post", "/v1/retrieval-contracts", _retrieval_create),
        ("patch", f"/v1/retrieval-contracts/{uuid.uuid4()}", _retrieval_patch),
    ],
)
def test_viewer_role_cannot_mutate_contract_records(
    method: str, path: str, payload_factory: Callable[[uuid.UUID], dict[str, object]]
) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    client = _build_client(tenant_id=tenant_id, roles=("viewer",))

    response = getattr(client, method)(path, json=payload_factory(mission_id))

    assert response.status_code == 403
    assert response.json()["detail"].startswith("missing permission:")
