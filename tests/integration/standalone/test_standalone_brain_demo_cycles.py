"""Ten-cycle standalone brain demo: Ajenda profile seed → retrieval → research."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile_projection import PROFILE_ACCOUNT_RECORD_ID
from backend.services.ajenda_demo_fixtures import seed_ajenda_live_demo
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

pytestmark = pytest.mark.integration

DEMO_CYCLE_COUNT = 10


@pytest.mark.parametrize("cycle", range(DEMO_CYCLE_COUNT))
def test_ajenda_standalone_brain_demo_cycle(pg_engine, cycle: int) -> None:
    tenant_id = f"tenant-demo-{cycle}-{uuid.uuid4().hex[:8]}"
    mission_id = uuid.uuid4()
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        seed_ajenda_live_demo(session=session, tenant_id=tenant_id)
        session.commit()
    finally:
        session.close()

    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=mission_id,
        worker_id="worker-demo",
        lease_id="lease-demo",
        session_factory=session_factory,
        vector_session_factory=session_factory,
    )
    registry = get_default_action_registry(rebuild=True)

    hybrid = registry.invoke(
        ToolInvocation(
            action="retrieval.hybrid_search",
            input={"query": "Ajenda AI", "mission_id": str(mission_id), "limit": 5},
        ),
        context,
    )
    assert hybrid.output["real"] is True
    assert hybrid.output["source"] == "ajenda_brain"
    memory_ids = {str(item.get("id")) for item in hybrid.output["memories"]}
    assert PROFILE_ACCOUNT_RECORD_ID in memory_ids or any(
        "Ajenda" in str(item.get("content")) for item in hybrid.output["memories"]
    )
    provenance = hybrid.evidence[0].provenance
    assert provenance.get("business_context", {}).get("business_name") == "Ajenda AI"

    search = registry.invoke(
        ToolInvocation(
            action="record.search",
            input={"record_type": "account", "query": "Ajenda", "limit": 5},
        ),
        context,
    )
    assert search.output["count"] >= 1
    assert PROFILE_ACCOUNT_RECORD_ID in search.evidence[0].records_inspected

    # Open-query research must not promote tenant profile into target company/domain.
    # Profile remains lineage-only (profile_company / profile_domain).
    research = registry.invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "Ajenda AI governed runtime", "limit": 3},
        ),
        context,
    )
    assert research.output["company"] is None
    assert research.output["domain"] is None
    assert research.output["profile_company"] == "Ajenda AI"
    assert research.output["profile_domain"] == "ajenda.ai"
    assert research.output["business_context_source"] == "business_profile"
