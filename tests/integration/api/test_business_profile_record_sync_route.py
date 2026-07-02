"""Business profile API upsert projects searchable internal records."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.routes import business_profile as business_profile_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID
from backend.domain.tenant import Tenant
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository

pytestmark = pytest.mark.integration


def _build_app(*, tenant_id: uuid.UUID, session: Session) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="integration-business-profile-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(business_profile_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> Session:
        return session

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def test_business_profile_upsert_syncs_internal_records(pg_session: Session) -> None:
    tenant_id = uuid.uuid4()
    tenant = Tenant(
        id=tenant_id,
        name="Profile Sync Tenant",
        slug=f"profile-sync-{tenant_id.hex[:8]}",
        plan="free",
    )
    pg_session.add(tenant)
    pg_session.commit()

    app = _build_app(tenant_id=tenant_id, session=pg_session)
    client = TestClient(app, raise_server_exceptions=True)

    response = client.put(
        "/v1/business-profile/facts/business_name",
        json={"approved_fact": {"value": "Cycle Roofing LLC"}, "provenance_metadata": {"source": "integration_test"}},
    )
    assert response.status_code == 200

    pg_session.expire_all()
    activate_tenant_session(pg_session, str(tenant_id))
    repo = TenantInternalRecordRepository(pg_session)
    account = repo.read_record(
        tenant_id=str(tenant_id),
        record_type="account",
        record_id=PROFILE_ACCOUNT_RECORD_ID,
    )
    assert account is not None
    assert account["name"] == "Cycle Roofing LLC"
