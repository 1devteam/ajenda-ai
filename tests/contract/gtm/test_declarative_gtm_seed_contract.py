from __future__ import annotations

from sqlalchemy import select

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter


def test_gtm_declarative_seed_contract_records_exist(pg_session) -> None:
    capabilities = pg_session.scalars(
        select(Capability).where(
            Capability.name.in_(
                [
                    "gtm.lead.discovery.query_builder",
                    "gtm.outbound.message_draft",
                    "gtm.content.publish_dispatch",
                ]
            )
        )
    ).all()
    adapters = pg_session.scalars(
        select(CapabilityAdapter).where(
            CapabilityAdapter.name.in_(
                [
                    "gtm.adapter.lead.query_builder",
                    "gtm.adapter.outbound.message_draft",
                    "gtm.adapter.content.publish_dispatch",
                ]
            )
        )
    ).all()

    assert len(capabilities) == 3
    assert len(adapters) == 3
    assert all(capability.tenant_id is None for capability in capabilities)
    assert all(adapter.tenant_id is None for adapter in adapters)
    assert all(adapter.execution_mode == "declarative" for adapter in adapters)
    assert all("runtime_binding_allowed" in capability.execution_constraints for capability in capabilities)
    assert all(capability.execution_constraints["runtime_binding_allowed"] is False for capability in capabilities)


def test_gtm_high_risk_contracts_seed_disabled(pg_session) -> None:
    publish_capability = pg_session.scalar(select(Capability).where(Capability.name == "gtm.content.publish_dispatch"))
    publish_adapter = pg_session.scalar(
        select(CapabilityAdapter).where(CapabilityAdapter.name == "gtm.adapter.content.publish_dispatch")
    )

    assert publish_capability is not None
    assert publish_adapter is not None
    assert publish_capability.enabled is False
    assert publish_adapter.enabled is False
    assert publish_adapter.side_effect_classification == "external_side_effect"
