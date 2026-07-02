from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.business_context_resolver import (
    BUSINESS_CONTEXT_CACHE_KEY,
    default_company_and_domain,
    resolve_business_context,
)
from backend.services.tools.schemas import ActionRuntimeContext

pytestmark = pytest.mark.integration


def test_resolve_business_context_caches_per_task(pg_engine) -> None:
    tenant_id = f"tenant-context-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        repo = BusinessProfileRepository(session)
        profile = repo.get_or_create_active_profile(tenant_id=tenant_id)
        repo.upsert_approved_fact(
            profile=profile,
            category="business_name",
            approved_fact={"value": "Blue River Plumbing"},
            actor_id="tester",
            updated_at=profile.updated_at,
        )
        repo.upsert_approved_fact(
            profile=profile,
            category="website",
            approved_fact={"value": "https://blueriverplumbing.com"},
            actor_id="tester",
            updated_at=profile.updated_at,
        )
        session.commit()
    finally:
        session.close()

    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=session_factory,
    )
    first = resolve_business_context(context)
    second = resolve_business_context(context)

    assert first.business_name == "Blue River Plumbing"
    assert first.domain == "blueriverplumbing.com"
    assert first is second
    assert BUSINESS_CONTEXT_CACHE_KEY in context.runtime_cache


def test_default_company_and_domain_falls_back_to_profile(pg_engine) -> None:
    tenant_id = f"tenant-defaults-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        repo = BusinessProfileRepository(session)
        profile = repo.get_or_create_active_profile(tenant_id=tenant_id)
        repo.upsert_approved_fact(
            profile=profile,
            category="business_name",
            approved_fact={"value": "North Peak Electric"},
            actor_id="tester",
            updated_at=profile.updated_at,
        )
        repo.upsert_approved_fact(
            profile=profile,
            category="website",
            approved_fact={"value": "northpeakelectric.com"},
            actor_id="tester",
            updated_at=profile.updated_at,
        )
        session.commit()
    finally:
        session.close()

    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=None,
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=session_factory,
    )
    company, domain = default_company_and_domain(context=context, company=None, domain=None)
    assert company == "North Peak Electric"
    assert domain == "northpeakelectric.com"
