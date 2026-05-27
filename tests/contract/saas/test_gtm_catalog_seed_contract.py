from __future__ import annotations

from sqlalchemy import select

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter


def test_global_gtm_capability_seed_contract(pg_session) -> None:
    seeded = (
        pg_session.execute(
            select(Capability)
            .where(Capability.tenant_id.is_(None), Capability.name.like("gtm.%"))
            .order_by(Capability.name)
        )
        .scalars()
        .all()
    )

    names = [row.name for row in seeded]
    assert names == [
        "gtm.lead.discovery.candidate_enrichment.v1",
        "gtm.lead.discovery.query_builder.v1",
        "gtm.outbound.send_dispatch.v1",
    ]

    send_dispatch = next(item for item in seeded if item.name == "gtm.outbound.send_dispatch.v1")
    assert send_dispatch.enabled is False
    assert send_dispatch.execution_constraints["runtime_binding"] == "forbidden_until_bundle_6_3"


def test_global_gtm_adapter_seed_contract(pg_session) -> None:
    adapters = (
        pg_session.execute(
            select(CapabilityAdapter)
            .where(CapabilityAdapter.tenant_id.is_(None), CapabilityAdapter.capability_name.like("gtm.%"))
            .order_by(CapabilityAdapter.capability_name)
        )
        .scalars()
        .all()
    )

    assert [item.capability_name for item in adapters] == [
        "gtm.lead.discovery.candidate_enrichment.v1",
        "gtm.lead.discovery.query_builder.v1",
        "gtm.outbound.send_dispatch.v1",
    ]
    assert all(item.execution_mode == "declarative" for item in adapters)

    adapter_by_name = {item.capability_name: item for item in adapters}

    assert (
        adapter_by_name["gtm.lead.discovery.query_builder.v1"].side_effect_classification == "none"
    )
    assert (
        adapter_by_name[
            "gtm.lead.discovery.candidate_enrichment.v1"
        ].side_effect_classification
        == "external_write"
    )
    assert (
        adapter_by_name["gtm.outbound.send_dispatch.v1"].side_effect_classification
        == "external_send"
    )
