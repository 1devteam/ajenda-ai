"""HTTP transaction proof for business-understanding recognition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.routes import business_understanding as business_understanding_module
from backend.app.config import get_settings
from backend.auth.principal import Principal, PrincipalType
from backend.db.session import DatabaseRuntime
from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_understanding import BusinessMeasurement, BusinessNeedRevision, BusinessObservation
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository

pytestmark = pytest.mark.integration


def _tenant() -> str:
    return str(uuid.uuid4())


def _app(*, tenant_id: str, roles: tuple[str, ...] = ("tenant_admin",)) -> FastAPI:
    app = FastAPI()
    app.state.database_runtime = DatabaseRuntime(get_settings())

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.tenant_id = tenant_id
        request.state.principal = Principal(
            subject_id="business-understanding-api-test",
            tenant_id=tenant_id,
            principal_type=PrincipalType.USER,
            roles=roles,
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


def _measurement_payload(*, current_value: float = 2, source_version: str = "v1") -> dict[str, object]:
    observed_at = datetime(2026, 1, 31, 12, tzinfo=UTC)
    subject = {"object_type": "organization", "object_id": "ajenda"}
    return {
        "goal": {
            "goal_id": "customer-acquisition",
            "objective_key": "customer_acquisition",
            "name": "Acquire qualified customers",
            "subject_refs": [subject],
        },
        "kpis": [
            {
                "kpi_id": "qualified-customers",
                "goal_id": "customer-acquisition",
                "name": "Qualified customers",
                "metric": "qualified_customers",
                "direction": "increase",
                "current_value": current_value,
                "target_value": 10,
                "previous_value": 3,
                "unit": "customers",
            }
        ],
        "subject_references": [subject],
        "source_kind": "customer_attested",
        "source_reference": {"source_id": "monthly-operating-statement"},
        "source_version": source_version,
        "measurement_period_start": "2026-01-01T00:00:00Z",
        "measurement_period_end": "2026-01-31T00:00:00Z",
        "observed_at": observed_at.isoformat(),
        "limitations": [{"code": "customer_attested_not_independently_verified"}],
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


def test_measurement_endpoint_persists_atomically_and_replays_without_duplicate_history(pg_engine) -> None:
    tenant_id = _tenant()
    app = _app(tenant_id=tenant_id)
    try:
        first = TestClient(app).post("/v1/business-understanding/measurements", json=_measurement_payload())
        replay = TestClient(app).post("/v1/business-understanding/measurements", json=_measurement_payload())
        assert first.status_code == replay.status_code == 201
        assert replay.json() == first.json()
        assert first.json()["source_kind"] == "customer_attested"
        assert first.json()["recognized_need_id"] is not None
        with pg_engine.connect() as connection:
            session = Session(bind=connection)
            activate_tenant_session(session, tenant_id)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessMeasurement)
                    .where(BusinessMeasurement.tenant_id == tenant_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessObservation)
                    .where(BusinessObservation.tenant_id == tenant_id)
                )
                == 1
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessNeedRevision)
                    .where(BusinessNeedRevision.tenant_id == tenant_id)
                )
                == 1
            )
            session.close()
    finally:
        app.state.database_runtime.dispose()


def test_measurement_endpoint_rejects_forged_provenance_and_subject_mismatch(pg_engine) -> None:
    tenant_id = _tenant()
    app = _app(tenant_id=tenant_id)
    try:
        verified = _measurement_payload()
        verified["source_kind"] = "source_verified"
        mismatched = _measurement_payload()
        mismatched["subject_references"] = [{"object_type": "organization", "object_id": "other"}]
        forged_response = TestClient(app).post("/v1/business-understanding/measurements", json=verified)
        mismatch_response = TestClient(app).post("/v1/business-understanding/measurements", json=mismatched)
        assert forged_response.status_code == 422
        assert mismatch_response.status_code == 422
        with pg_engine.connect() as connection:
            session = Session(bind=connection)
            activate_tenant_session(session, tenant_id)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessMeasurement)
                    .where(BusinessMeasurement.tenant_id == tenant_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessObservation)
                    .where(BusinessObservation.tenant_id == tenant_id)
                )
                == 0
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessNeedRevision)
                    .where(BusinessNeedRevision.tenant_id == tenant_id)
                )
                == 0
            )
            session.close()
    finally:
        app.state.database_runtime.dispose()


def test_measurement_endpoint_denies_authenticated_viewer(pg_engine) -> None:
    tenant_id = _tenant()
    app = _app(tenant_id=tenant_id, roles=("viewer",))
    try:
        response = TestClient(app).post("/v1/business-understanding/measurements", json=_measurement_payload())
        assert response.status_code == 403
        with pg_engine.connect() as connection:
            session = Session(bind=connection)
            activate_tenant_session(session, tenant_id)
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(BusinessMeasurement)
                    .where(BusinessMeasurement.tenant_id == tenant_id)
                )
                == 0
            )
            session.close()
    finally:
        app.state.database_runtime.dispose()
