from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

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
