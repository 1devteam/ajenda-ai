"""HTTP transaction proof for business-understanding recognition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.routes import business_understanding as business_understanding_module
from backend.app.config import get_settings
from backend.auth.principal import Principal, PrincipalType
from backend.db.session import DatabaseRuntime
from backend.db.tenant_session import activate_tenant_session
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository

pytestmark = pytest.mark.integration


def _tenant() -> str:
    return str(uuid.uuid4())


def _app(*, tenant_id: str) -> FastAPI:
    app = FastAPI()
    app.state.database_runtime = DatabaseRuntime(get_settings())

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = Principal(
            subject_id="business-understanding-api-test",
            tenant_id=tenant_id,
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(business_understanding_module.router, prefix="/v1")
    return app


def _recognition_payload(*, forbidden_response: bool = False) -> dict[str, object]:
    return {
        "observation": {
            "source_kind": "external_provider",
            "source_reference": {"source_id": "fixture-acquisition-measurement"},
            "observation_summary": "Customer acquisition is below the observed target.",
            "observed_at": datetime.now(UTC).isoformat(),
            "limitations": [{"code": "CAUSE_UNVERIFIED"}],
        },
        "need": {
            "expected_revision": 0,
            "origin": "observed",
            "condition_summary": "Customer acquisition may require attention.",
            "candidate_responses": [
                {
                    "response_key": "investigate-acquisition-causes",
                    "grants_execution_authority": forbidden_response,
                }
            ],
        },
    }


def _tenant_records(pg_engine, tenant_id: str):
    with pg_engine.connect() as connection:
        session = Session(bind=connection, expire_on_commit=False)
        try:
            activate_tenant_session(session, tenant_id)
            repository = BusinessUnderstandingRepository(session)
            observations = repository.list_observations_for_tenant(tenant_id=tenant_id)
            needs = repository.list_latest_needs_for_tenant(tenant_id=tenant_id)
            return (
                [{"producer": observation.producer} for observation in observations],
                [{"producer": need.producer} for need in needs],
            )
        finally:
            session.rollback()
            session.close()


def test_recognition_endpoint_commits_observation_and_need_with_one_tenant_producer(pg_engine) -> None:
    tenant_id = _tenant()
    app = _app(tenant_id=tenant_id)
    try:
        with patch.object(business_understanding_module, "require_route_permission", return_value=None):
            response = TestClient(app).post(
                "/v1/business-understanding/recognitions",
                json=_recognition_payload(),
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["revision"] == 1
        assert body["producer"] == "business-understanding-api-test"
        assert body["grants_execution_authority"] is False
        observations, needs = _tenant_records(pg_engine, tenant_id)
        assert len(observations) == len(needs) == 1
        assert observations[0]["producer"] == needs[0]["producer"] == "business-understanding-api-test"
    finally:
        app.state.database_runtime.dispose()


def test_recognition_endpoint_rolls_back_its_observation_when_need_validation_fails(pg_engine) -> None:
    tenant_id = _tenant()
    app = _app(tenant_id=tenant_id)
    try:
        with patch.object(business_understanding_module, "require_route_permission", return_value=None):
            response = TestClient(app).post(
                "/v1/business-understanding/recognitions",
                json=_recognition_payload(forbidden_response=True),
            )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "BUSINESS_UNDERSTANDING_INVALID"
        observations, needs = _tenant_records(pg_engine, tenant_id)
        assert observations == needs == []
    finally:
        app.state.database_runtime.dispose()
