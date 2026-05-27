from __future__ import annotations

from sqlalchemy import select

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter


def test_gtm_catalog_seed_contract(pg_session) -> None:
    send_capability = pg_session.execute(
        select(Capability).where(Capability.name == "gtm.outbound.send_dispatch", Capability.version == "1.0.0")
    ).scalar_one()
    assert send_capability.execution_constraints["side_effect_class"] == "external_send"

    send_adapter = pg_session.execute(
        select(CapabilityAdapter).where(
            CapabilityAdapter.name == "gtm.adapter.outbound.send_dispatch.declarative",
            CapabilityAdapter.version == "1.0.0",
        )
    ).scalar_one()
    assert send_adapter.side_effect_classification == "external_side_effect"

    draft_capability = pg_session.execute(
        select(Capability).where(Capability.name == "gtm.outbound.message_draft", Capability.version == "1.0.0")
    ).scalar_one()
    assert draft_capability.execution_constraints["side_effect_class"] == "none"

    draft_adapter = pg_session.execute(
        select(CapabilityAdapter).where(
            CapabilityAdapter.name == "gtm.adapter.outbound.message_draft.declarative",
            CapabilityAdapter.version == "1.0.0",
        )
    ).scalar_one()
    assert draft_adapter.side_effect_classification == "none"
