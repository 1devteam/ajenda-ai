"""Profile save projects searchable tenant_internal_records for hybrid retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.business_profile_record_sync import sync_profile_to_internal_records
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

pytestmark = pytest.mark.integration


def test_sync_profile_to_internal_records_is_idempotent(pg_engine) -> None:
    tenant_id = f"tenant-sync-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    facts = {
        "business_name": {"value": "Summit HVAC"},
        "primary_contact_name": {"value": "Alex Morgan"},
        "contact_email": {"value": "ops@summithvac.com"},
    }

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        first = sync_profile_to_internal_records(session=session, tenant_id=tenant_id, approved_facts=facts)
        second = sync_profile_to_internal_records(session=session, tenant_id=tenant_id, approved_facts=facts)
        session.commit()
    finally:
        session.close()

    assert first == [PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID]
    assert second == [PROFILE_ACCOUNT_RECORD_ID, PROFILE_CONTACT_RECORD_ID]

    verify = session_factory()
    try:
        activate_tenant_session(verify, tenant_id)
        repo = TenantInternalRecordRepository(verify)
        account = repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=PROFILE_ACCOUNT_RECORD_ID,
        )
        contact = repo.read_record(
            tenant_id=tenant_id,
            record_type="contact",
            record_id=PROFILE_CONTACT_RECORD_ID,
        )
    finally:
        verify.close()

    assert account is not None
    assert account["name"] == "Summit HVAC"
    assert contact is not None
    assert contact["email"] == "ops@summithvac.com"


def test_profile_synced_records_are_discoverable_via_hybrid_search(pg_engine) -> None:
    tenant_id = f"tenant-profile-sync-{uuid.uuid4().hex[:8]}"
    mission_id = uuid.uuid4()
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        repo = BusinessProfileRepository(session)
        profile = repo.get_or_create_active_profile(tenant_id=tenant_id)
        now = datetime.now(UTC)
        repo.upsert_approved_fact(
            profile=profile,
            category="business_name",
            approved_fact={"value": "Cedar Creek Landscaping"},
            actor_id="operator",
            updated_at=now,
        )
        repo.upsert_approved_fact(
            profile=profile,
            category="service_area",
            approved_fact={"value": "Round Rock, Texas"},
            actor_id="operator",
            updated_at=now,
        )
        sync_profile_to_internal_records(
            session=session,
            tenant_id=tenant_id,
            approved_facts=profile.approved_facts or {},
        )
        session.commit()
    finally:
        session.close()

    verify = session_factory()
    try:
        activate_tenant_session(verify, tenant_id)
        internal_repo = TenantInternalRecordRepository(verify)
        internal_repo.seed_defaults_if_empty(tenant_id=tenant_id)
        account = internal_repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=PROFILE_ACCOUNT_RECORD_ID,
        )
        assert account is not None
        assert account["name"] == "Cedar Creek Landscaping"
        from backend.services.ajenda_demo_fixtures import DEMO_PROSPECT_ACCOUNT_ID

        demo = internal_repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=DEMO_PROSPECT_ACCOUNT_ID,
        )
        assert demo is None
    finally:
        verify.close()

    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="retrieval.hybrid_search",
            input={"query": "Cedar Creek", "mission_id": str(mission_id), "limit": 5},
        ),
        ActionRuntimeContext(
            tenant_id=tenant_id,
            task_id=uuid.uuid4(),
            mission_id=mission_id,
            worker_id="worker-1",
            lease_id="lease-1",
            session_factory=session_factory,
            vector_session_factory=session_factory,
        ),
    )

    memory_ids = {str(item.get("id")) for item in result.output["memories"]}
    assert PROFILE_ACCOUNT_RECORD_ID in memory_ids or any(
        "Cedar Creek" in str(item.get("content")) for item in result.output["memories"]
    )
    provenance = result.evidence[0].provenance
    assert provenance.get("business_context", {}).get("business_name") == "Cedar Creek Landscaping"


def test_internal_crm_write_is_durable_idempotent_and_tenant_scoped(pg_engine) -> None:
    tenant_id = f"tenant-internal-crm-{uuid.uuid4().hex[:8]}"
    other_tenant_id = f"tenant-internal-crm-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-internal-crm",
        lease_id=str(uuid.uuid4()),
        session_factory=session_factory,
    )
    invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "contact",
            "context": {
                "prospect_candidates": [
                    {"prospect_id": "durable-prospect-1", "company": "Durable Roofing", "domain": "durable.test"}
                ],
                "observed_contacts": [
                    {
                        "prospect_id": "durable-prospect-1",
                        "email": "owner@durable.test",
                        "source_url": "https://durable.test/contact",
                    }
                ],
            },
        },
    )
    registry = get_default_action_registry(rebuild=True)

    first = registry.invoke(invocation, context)
    second = registry.invoke(invocation, context)
    record_id = first.records_changed[0]

    assert first.output["internal_crm_records"][0]["operation"] == "created"
    assert second.output["internal_crm_records"][0]["operation"] == "unchanged"
    assert second.output["crm_readback_records"][0]["verified"] is True
    projection = second.output["crm_projection_records"][0]
    assert projection["contact_id"] == record_id
    assert projection["account_id"]
    assert projection["opportunity_id"]
    assert len(projection["activity_ids"]) == 1

    verify = session_factory()
    try:
        activate_tenant_session(verify, tenant_id)
        repo = TenantInternalRecordRepository(verify)
        own = repo.read_record(
            tenant_id=tenant_id, record_type="contact", record_id=record_id
        )
        account = repo.read_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id=str(own.get("account_id")) if own else "",
        )
        opportunities = repo.search_records(
            tenant_id=tenant_id,
            record_type="opportunity",
            filters={"contact_id": record_id},
            limit=10,
        )
        activities = repo.list_activities_for_record(
            tenant_id=tenant_id,
            related_type="contact",
            related_id=record_id,
            limit=10,
        )
    finally:
        verify.close()
    other = session_factory()
    try:
        activate_tenant_session(other, other_tenant_id)
        foreign = TenantInternalRecordRepository(other).read_record(
            tenant_id=other_tenant_id, record_type="contact", record_id=record_id
        )
    finally:
        other.close()

    assert own is not None and own["company"] == "Durable Roofing"
    assert own["lifecycle_stage"] == "observed"
    assert account is not None and account["name"] == "Durable Roofing"
    assert len(opportunities) == 1
    assert len(activities) == 1
    assert foreign is None
