from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.services.knowledge import ContextConditionState, SourceConditionObservation
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import ActionRegistry, get_default_action_registry
from backend.services.tools.local_records import default_local_record_provider
from backend.services.tools.sales_actions import register_sales_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def test_sales_and_record_actions_return_evidence_shaped_output() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(action="record.search", input={"record_type": "account", "query": "Ajenda"}), context
    )

    assert result.output["count"] >= 1
    assert result.evidence[0].action_name == "record.search"
    assert result.evidence[0].tenant_id == context.tenant_id
    assert result.evidence[0].lineage is not None
    assert result.evidence[0].lineage.origin_type.value == "source_observation"
    assert "profile-account-primary" in result.evidence[0].records_inspected


def test_record_search_exposes_verified_internal_crm_prospects() -> None:
    context = _context()
    default_local_record_provider().seed_tenant(
        context.tenant_id,
        {
            "account": {
                "acct-1": {
                    "id": "acct-1",
                    "name": "Example HVAC",
                    "website": "https://example-hvac.test",
                },
            },
            "contact": {
                "contact-1": {
                    "id": "contact-1",
                    "account_id": "acct-1",
                    "email": "owner@example-hvac.test",
                },
            },
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(action="record.search", input={"record_type": "account", "query": ""}), context
    )

    normalized = next(item for item in result.output["crm_records"] if item.get("id") == "acct-1")
    assert normalized["company"] == "Example HVAC"
    assert normalized["source"] == "internal_record"
    assert normalized["identity_status"] == "verified"
    assert normalized["contacts"][0]["email"] == "owner@example-hvac.test"
    assert result.output["records"] != result.output["crm_records"]


def test_record_read_emits_typed_source_condition_semantics() -> None:
    context = _context()
    observed_at = "2026-08-13T00:00:00+00:00"
    default_local_record_provider().seed_tenant(
        context.tenant_id,
        {
            "opportunity": {
                "opp-1": {
                    "id": "opp-1",
                    "condition_observations": [
                        {
                            "condition_key": "segment:smb",
                            "state": "active",
                            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-1"}],
                            "observed_at": observed_at,
                            "verification_basis": "source_supplied_under_contract",
                        }
                    ],
                }
            }
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(action="record.read", input={"record_type": "opportunity", "record_id": "opp-1"}),
        context,
    )

    observation = SourceConditionObservation.model_validate(
        result.evidence[0].structured_payload["condition_observations"][0]
    )
    assert observation.condition_key == "segment:smb"
    assert observation.state == ContextConditionState.ACTIVE
    assert observation.subject_refs[0].object_id == "opp-1"
    assert observation.observed_at == datetime(2026, 8, 13, tzinfo=UTC)
    assert result.evidence[0].lineage is not None
    assert result.evidence[0].lineage.resolution.value == "known"
    assert result.evidence[0].lineage.source_identity is not None
    assert result.evidence[0].lineage.source_identity.source_system == "tenant_record_store"
    assert result.evidence[0].lineage.source_identity.source_record_id == "opportunity:opp-1"


def test_sales_qualify_rejects_snippet_only_prospects() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "company": "Hazmat Removal Service",
                        "url": "https://www.nwarestoreit.com/hazmat-service",
                        "domain": "nwarestoreit.com",
                        "source": "public_search",
                        "signals": ["snippet only"],
                    }
                ]
            },
        ),
        _context(),
    )
    assert result.output["qualified"] is False
    assert result.output["qualified_prospects"] == []
    assert "not qualified without an observed or supplied contact" in result.output["reasons"]


def test_sales_qualify_accepts_observed_email() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "company": "NWA Restore It",
                        "kind": "email",
                        "value": "hello@nwarestoreit.com",
                        "source_url": "https://www.nwarestoreit.com/hazmat-service",
                        "website": "https://www.nwarestoreit.com",
                        "product_description": "Property restoration services.",
                        "research_summary": "NWA Restore It serves restoration customers.",
                        "sources": ["https://www.nwarestoreit.com/hazmat-service"],
                        "automation_opportunity": "estimate follow-up",
                        "real": True,
                    }
                ]
            },
        ),
        _context(),
    )
    assert result.output["qualified"] is True
    qualified = result.output["qualified_prospects"][0]
    assert qualified["email"] == "hello@nwarestoreit.com"
    assert qualified["website"] == "https://www.nwarestoreit.com"
    assert qualified["product_description"] == "Property restoration services."
    assert qualified["research_summary"] == "NWA Restore It serves restoration customers."
    assert qualified["sources"] == ["https://www.nwarestoreit.com/hazmat-service", "https://www.nwarestoreit.com"]
    assert qualified["qualification_evidence"]["qualification_dimensions"] == qualified["qualification_dimensions"]
    assert qualified["qualification_evidence"]["source_references"] == qualified["sources"]
    assert "estimate follow-up" in qualified["ajenda_relevance"]


def test_sales_qualify_joins_observed_contacts_to_prospects() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "prospect_id": "account-1",
                        "company": "Austin Software Studio",
                        "source": "internal_record",
                        "industry": "software development",
                        "location": "Austin",
                    }
                ],
                "context": {
                    "observed_contacts": [
                        {
                            "prospect_id": "account-1",
                            "kind": "email",
                            "value": "founder@austin-studio.example",
                            "real": True,
                        }
                    ]
                },
            },
        ),
        _context(),
    )
    assert result.output["prospect_count"] == 1
    assert result.output["qualified_prospects"][0]["email"] == "founder@austin-studio.example"


def test_sales_qualify_applies_mission_scope_to_every_bound_prospect() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "prospect_id": "p1",
                        "company": "One HVAC",
                        "identity_status": "verified",
                        "url": "https://one.example",
                    },
                    {
                        "prospect_id": "p2",
                        "company": "Two HVAC",
                        "identity_status": "verified",
                        "url": "https://two.example",
                    },
                ],
                "context": {
                    "industry": "HVAC",
                    "location": "Dallas",
                    "requested_quantity": 1,
                    "qualification_threshold_10": 5,
                    "mission_specific_scoring": True,
                    "observed_contacts": [
                        {"prospect_id": "p1", "kind": "phone", "value": "214-555-0100", "real": True},
                        {"prospect_id": "p2", "kind": "phone", "value": "214-555-0101", "real": True},
                    ],
                },
            },
        ),
        _context(),
    )
    assert len(result.output["scored_prospects"]) == 2
    assert len(result.output["qualified_prospects"]) == 1
    assert result.output["qualified_prospects"][0]["score_10"] == 5


def test_sales_ranking_accepts_verified_identity_without_contact() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "company": "Verified HVAC",
                        "identity_status": "verified",
                        "url": "https://verified-hvac.example",
                        "source": "public_search",
                    }
                ],
                "context": {
                    "mission_specific_scoring": True,
                    "ranking_only": True,
                    "qualification_threshold_10": 7,
                },
            },
        ),
        _context(),
    )

    assert len(result.output["qualified_prospects"]) == 1
    assert result.output["qualified_prospects"][0]["qualified"] is True
    assert result.output["qualified_prospects"][0]["identity_status"] == "verified"


def test_sales_qualify_exposes_mission_dimensions_and_rejects_unverified_identity() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="sales.qualify",
            input={
                "prospects": [
                    {
                        "company": "Directory HVAC Listing",
                        "domain": "directory.example",
                        "identity_status": "unverified",
                        "url": "https://directory.example/hvac",
                        "email": "owner@directory.example",
                        "automation_opportunity": "estimate follow-up",
                    }
                ],
                "context": {"qualification_threshold_10": 7},
            },
        ),
        _context(),
    )

    assert result.output["qualified"] is False
    assert result.output["score_10"] >= 0
    assert set(result.output["qualification_dimensions"]) == {
        "business_fit",
        "automation_opportunity",
        "evidence_quality",
        "urgency",
    }
    assert "identity is unverified" in result.output["reasons"]


def test_sales_qualify_score_and_recommendation_are_deterministic() -> None:
    registry = get_default_action_registry(rebuild=True)
    context = _context()
    lead = {"company": "Acme", "role": "VP", "intent": "expansion", "email": "avery@example.com"}

    score = registry.invoke(ToolInvocation(action="sales.score_lead", input={"lead": lead}), context)
    recommendation = registry.invoke(
        ToolInvocation(action="sales.recommend_next_action", input={"lead": lead}), context
    )

    assert score.output == {
        "lead_score": 100,
        "score_band": "high",
        "reasons": [
            "company/account context present",
            "buyer role context present",
            "intent signal present",
            "contactability present",
        ],
    }
    assert recommendation.output["recommendation"] == "draft_followup"


def test_aliases_map_to_sales_actions() -> None:
    registry = get_default_action_registry(rebuild=True)

    research = registry.invoke(
        ToolInvocation(action="crm.research", input={"lead": {"account_id": "acct-1"}}), _context()
    )
    draft = registry.invoke(
        ToolInvocation(action="gtm.message_draft", input={"recipient_name": "Avery", "topic": "pilot"}), _context()
    )

    assert research.action == "sales.research"
    assert "Drafted" in draft.summary


def test_record_write_is_observable_by_read() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    write_result = registry.invoke(
        ToolInvocation(
            action="record.write",
            input={
                "record_type": "contact",
                "record_id": "contact-new",
                "data": {"name": "New Contact", "role": "Buyer"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "contact", "record_id": "contact-new"},
        ),
        context,
    )

    assert write_result.records_changed == ["contact-new"]
    executed_at = datetime.fromisoformat(write_result.output["executed_at"])
    assert executed_at.tzinfo is not None and executed_at.utcoffset() is not None
    assert write_result.evidence[0].structured_payload["executed_at"] == write_result.output["executed_at"]
    assert read_result.output["found"] is True
    assert read_result.output["record"]["name"] == "New Contact"


def test_internal_crm_record_write_is_idempotent_and_readback_verified() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()
    invocation = ToolInvocation(
        action="record.write",
        input={
            "record_type": "contact",
            "context": {
                "source": "mission_composition",
                "qualified_prospects": [
                    {"prospect_id": "prospect-1", "company": "Acme Roofing", "domain": "acme.test"}
                ],
                "observed_contacts": [
                    {"prospect_id": "prospect-1", "email": "owner@acme.test", "source_url": "https://acme.test"}
                ],
            },
        },
    )

    first = registry.invoke(invocation, context)
    second = registry.invoke(invocation, context)

    assert first.output["internal_crm_records"][0]["operation"] == "created"
    assert second.output["internal_crm_records"][0]["operation"] == "unchanged"
    assert first.records_changed == second.records_changed
    assert second.output["readback_verified_count"] == 1
    assert second.output["crm_readback_records"][0]["verified"] is True


def test_internal_crm_record_write_consumes_enriched_prospects() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()
    result = registry.invoke(
        ToolInvocation(
            action="record.write",
            input={
                "record_type": "contact",
                "context": {
                    "source": "mission_composition",
                    "qualified_prospects": [
                        {"prospect_id": "prospect-1", "company": "Acme HVAC", "domain": "acme.test"}
                    ],
                    "enriched_prospects": [
                        {
                            "prospect_id": "prospect-1",
                            "company": "Acme HVAC",
                            "domain": "acme.test",
                            "contacts": [{"email": "owner@acme.test", "real": True}],
                            "enrichment_real": True,
                            "enrichment_mode": "passthrough_observed",
                        }
                    ],
                },
            },
        ),
        context,
    )

    persisted = result.output["internal_crm_records"][0]
    assert persisted["enrichment_real"] is True
    assert persisted["enrichment_mode"] == "passthrough_observed"
    assert persisted["contacts"][0]["email"] == "owner@acme.test"


def test_internal_crm_record_write_rejects_unqualified_candidates() -> None:
    context = _context()
    with pytest.raises(ValueError, match="requires at least one qualified prospect"):
        get_default_action_registry(rebuild=True).invoke(
            ToolInvocation(
                action="record.write",
                input={
                    "record_type": "contact",
                    "context": {
                        "source": "mission_composition",
                        "prospect_candidates": [{"prospect_id": "raw-1", "company": "Unqualified"}],
                        "qualified_prospects": [],
                    },
                },
            ),
            context,
        )


def test_internal_crm_record_write_rejects_tenant_mismatch() -> None:
    context = _context()
    with pytest.raises(ValueError, match="must match the runtime tenant"):
        get_default_action_registry(rebuild=True).invoke(
            ToolInvocation(
                action="record.write",
                input={"record_type": "contact", "tenant_id": "another-tenant", "data": {"name": "Acme"}},
            ),
            context,
        )


def test_sales_log_activity_preserves_record_write_payload_shape() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(
            action="sales.log_activity",
            input={
                "record_type": "activity",
                "record_id": "activity-1",
                "data": {"note": "called buyer", "channel": "phone"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "activity", "record_id": "activity-1"},
        ),
        context,
    )

    assert result.records_changed == ["activity-1"]
    assert read_result.output["record"] == {
        "id": "activity-1",
        "note": "called buyer",
        "channel": "phone",
    }


def test_sales_research_consumes_bound_prospect_candidates() -> None:
    from backend.services.plugins.crm_client import CrmSearchResult

    client = MagicMock()
    client.search.side_effect = [
        CrmSearchResult(
            results=[{"id": "crm-alpha", "company": "Alpha Roofing"}],
            count=1,
            source="ajenda_brain",
            real=True,
        ),
        CrmSearchResult(
            results=[{"id": "crm-beta", "company": "Beta Roofing"}],
            count=1,
            source="ajenda_brain",
            real=True,
        ),
    ]
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("sales.research").handler
    invocation = ToolInvocation(
        action="sales.research",
        input={
            "lead": {"company": "roofing companies (Austin)"},
            "context": {
                "prospect_candidates": [
                    {"prospect_id": "p1", "company": "Alpha Roofing", "domain": "alpha.example"},
                    {"prospect_id": "p2", "company": "Beta Roofing", "domain": "beta.example"},
                ]
            },
        },
    )

    with patch("backend.services.tools.sales_actions.default_crm_client", return_value=client):
        result = handler(invocation, _context())

    assert client.search.call_count == 2
    assert client.search.call_args_list[0].kwargs["company"] == "Alpha Roofing"
    assert client.search.call_args_list[0].kwargs["domain"] == "alpha.example"
    assert client.search.call_args_list[1].kwargs["company"] == "Beta Roofing"
    assert [item["prospect_id"] for item in result.output["researched_prospects"]] == ["p1", "p2"]
    assert result.output["researched_prospects"][0]["crm_matches"][0]["id"] == "crm-alpha"
    assert result.output["researched_prospects"][1]["crm_matches"][0]["id"] == "crm-beta"
    assert [item["id"] for item in result.output["crm_matches"]] == ["crm-alpha", "crm-beta"]
    assert result.records_inspected == ["crm-alpha", "crm-beta"]


def test_sales_research_bound_prospect_refuses_tenant_profile_substitution() -> None:
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("sales.research").handler

    with pytest.raises(ValueError, match="refusing tenant-profile substitution"):
        handler(
            ToolInvocation(
                action="sales.research",
                input={"context": {"prospect_candidates": [{"prospect_id": "p1"}]}},
            ),
            _context(),
        )


def test_sales_research_credentialed_uses_external_read_path() -> None:
    registry = ActionRegistry()
    register_sales_actions(registry)
    handler = registry.get("sales.research").handler
    context = _context()
    context.runtime_credentials = {
        "sales.research": {
            "secret_value": "crm-token",
            "trusted_destination_hosts": ["api.crm.example.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://api.crm.example.com/v1/search",
        connect_url="https://1.2.3.4/v1/search",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.crm.example.com",
        host_header="api.crm.example.com",
    )
    response = NetworkEgressResponse(status_code=200, headers={}, body_text='{"results":[]}', body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="sales.research",
                input={"lead": {"company": "Acme"}},
                idempotency_key="idem-crm-1",
                credential_reference={
                    "credential_id": "crm-cred",
                    "provider": "external_crm",
                    "credential_type": "api_key",
                },
            ),
            context,
        )

    assert result.provider == "ajenda_brain"
    assert result.side_effect_class.value == "external_read"
    assert result.output["real"] is True
    assert result.output["plugin_required"] is True
    assert authority.request.call_args.kwargs["headers"]["Idempotency-Key"] == "idem-crm-1"


def test_sales_research_hubspot_adapter_source_counts_as_external_plugin() -> None:
    registry = get_default_action_registry(rebuild=True)
    handler = registry.get("sales.research").handler
    context = _context()
    context.runtime_credentials = {
        "sales.research": {
            "secret_value": "crm-token",
            "trusted_destination_hosts": ["hubspot-crm-ingress"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://hubspot-crm-ingress/v1/search",
        connect_url="https://10.0.0.2/v1/search",
        pinned_ip=__import__("ipaddress").ip_address("10.0.0.2"),
        sni_hostname="hubspot-crm-ingress",
        host_header="hubspot-crm-ingress",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"results":[{"id":"330345792208"}],"count":1,"source":"hubspot"}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="crm.research",
                input={"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
            ),
            context,
        )

    assert result.output["plugin_required"] is True
    assert result.output["source"] == "hubspot"
    assert "via external plugin" in result.summary


def test_sales_research_local_path_uses_ajenda_brain() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(action="sales.research", input={"lead": {"company": "Acme"}}),
        _context(),
    )

    assert result.provider == "ajenda_brain"
    assert result.side_effect_class.value == "internal_read"
    assert result.output["real"] is True
    assert result.output["plugin_required"] is False


def test_sales_create_followup_task_preserves_record_write_payload_shape() -> None:
    from backend.services.tools.local_records import reset_default_local_record_provider

    reset_default_local_record_provider()
    registry = get_default_action_registry(rebuild=True)
    context = _context()

    result = registry.invoke(
        ToolInvocation(
            action="sales.create_followup_task",
            input={
                "record_type": "task",
                "record_id": "task-1",
                "data": {"title": "Follow up", "due": "2026-06-06"},
            },
        ),
        context,
    )
    read_result = registry.invoke(
        ToolInvocation(
            action="record.read",
            input={"record_type": "task", "record_id": "task-1"},
        ),
        context,
    )

    assert result.records_changed == ["task-1"]
    assert read_result.output["record"] == {
        "id": "task-1",
        "title": "Follow up",
        "due": "2026-06-06",
    }
