from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository

pytestmark = pytest.mark.integration


def test_seeded_gtm_catalog_rows_are_tenant_visible_and_match_contract_shapes(pg_session: Session) -> None:
    tenant_id = str(uuid.uuid4())

    capability_repo = CapabilityRepository(pg_session)
    adapter_repo = CapabilityAdapterRepository(pg_session)

    capabilities = capability_repo.list_visible_for_tenant(tenant_id=tenant_id)
    adapters = adapter_repo.list_visible_for_tenant(tenant_id=tenant_id)

    seeded_capability = next(
        capability
        for capability in capabilities
        if capability.tenant_id is None and capability.name == "gtm_outbound_email" and capability.version == "1.0.0"
    )
    seeded_adapter = next(
        adapter
        for adapter in adapters
        if adapter.tenant_id is None and adapter.name == "gtm_outbound_email_adapter" and adapter.version == "1.0.0"
    )

    assert seeded_capability.evidence_expectations == ["approval_decision", "send_outcome"]
    assert seeded_adapter.evidence_expectations == ["approval_decision", "delivery_outcome"]
    assert seeded_adapter.capability_id == seeded_capability.id
