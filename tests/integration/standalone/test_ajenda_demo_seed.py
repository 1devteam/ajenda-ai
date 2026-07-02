"""Ajenda AI live demo seeds profile truth and searchable internal records."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.ajenda_demo_fixtures import DEMO_PROSPECT_ACCOUNT_ID

pytestmark = pytest.mark.integration


def test_seed_defaults_if_empty_bootstraps_ajenda_self_selling_demo(pg_engine) -> None:
    tenant_id = f"tenant-ajenda-demo-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        record_repo = TenantInternalRecordRepository(session)
        record_repo.seed_defaults_if_empty(tenant_id=tenant_id)
        session.commit()
    finally:
        session.close()

    verify = session_factory()
    try:
        activate_tenant_session(verify, tenant_id)
        profile = BusinessProfileRepository(verify).get_active_profile_for_tenant(tenant_id=tenant_id)
        record_repo = TenantInternalRecordRepository(verify)
        account = record_repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=PROFILE_ACCOUNT_RECORD_ID,
        )
        prospect = record_repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=DEMO_PROSPECT_ACCOUNT_ID,
        )
        matches = record_repo.search_records(
            tenant_id=tenant_id,
            record_type="account",
            query="Ajenda",
            limit=5,
        )
    finally:
        verify.close()

    assert profile is not None
    assert profile.approved_facts.get("business_name") == {"value": "Ajenda AI"}
    assert account is not None
    assert account["name"] == "Ajenda AI"
    assert prospect is not None
    assert prospect["interest"]
    assert any(item.get("id") == PROFILE_ACCOUNT_RECORD_ID for item in matches)
