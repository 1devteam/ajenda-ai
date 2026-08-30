from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import (
    ActionRuntimeContext,
    CredentialReference,
    RuntimeCredentialMaterial,
    ToolInvocation,
)


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )


def test_gtm_lead_enrich_returns_evidence_without_side_effect() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.lead_enrich",
            input={"company": "Acme", "domain": "acme.com"},
        ),
        _context(),
    )

    assert result.side_effect_class.value == "none"
    assert result.output["company"] == "Acme"
    assert len(result.evidence) == 1
    assert result.output["contacts"] == []
    assert result.output["simulated"] is False
    assert "contact@acme.com" not in str(result.output)


def test_gtm_lead_enrich_rejects_missing_target_instead_of_using_business_profile() -> None:
    registry = get_default_action_registry(rebuild=True)

    with pytest.raises(ValueError, match=r"invalid input for action gtm\.lead_enrich"):
        registry.invoke(
            ToolInvocation(action="gtm.lead_enrich", input={}),
            _context(),
        )


def test_gtm_lead_enrich_accepts_bound_prospect_without_profile_fallback() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.lead_enrich",
            input={"prospects": [{"company": "Bound Prospect", "domain": "prospect.invalid"}]},
        ),
        _context(),
    )

    assert result.output["company"] == "Bound Prospect"
    assert result.output["domain"] == "prospect.invalid"


def test_gtm_lead_enrich_rejects_unbound_composed_input() -> None:
    registry = get_default_action_registry(rebuild=True)

    with pytest.raises(ValueError, match="requires bound upstream prospects"):
        registry.invoke(
            ToolInvocation(
                action="gtm.lead_enrich",
                input={
                    "company": "Generic Prospect Company",
                    "context": {"binding_required": True},
                },
            ),
            _context(),
        )


def test_gtm_email_draft_fans_out_one_artifact_row_per_prospect() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.email_draft",
            input={
                "prospects": [
                    {"prospect_id": "p1", "company": "Alpha HVAC"},
                    {"prospect_id": "p2", "company": "Beta HVAC"},
                ]
            },
        ),
        _context(),
    )

    assert result.output["draft_count"] == 2
    assert [row["prospect_id"] for row in result.output["introduction_drafts"]] == ["p1", "p2"]
    assert [row["company"] for row in result.output["introduction_drafts"]] == ["Alpha HVAC", "Beta HVAC"]


def test_gtm_lead_enrich_simulates_only_when_explicitly_allowed(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_ENV", "development")
    monkeypatch.setenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", "1")
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.lead_enrich",
            input={"company": "Acme", "domain": "acme.com"},
        ),
        _context(),
    )
    assert result.output["simulated"] is True
    assert result.output["contacts"][0]["email"] == "contact@acme.com"
    assert result.output["contacts"][0]["real"] is False


def test_gtm_email_send_simulated_when_no_credential() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.email_send",
            input={"to": "user@example.com", "subject": "Hello", "body": "Hi"},
        ),
        _context(),
    )

    assert result.output["real"] is False
    assert result.output["status"] == "simulated"
    assert result.output["sent_messages"] == [
        {
            "to": "user@example.com",
            "subject": "Hello",
            "artifact_id": None,
            "status": "simulated",
            "real": False,
            "provider": None,
            "reason": "no_runtime_credential",
        }
    ]
    assert result.side_effect_class.value == "external_send"


def test_gtm_email_send_review_block_emits_canonical_attempt_artifact() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    session = MagicMock()
    context = _context()
    context.session_factory = lambda: session

    with patch(
        "backend.services.tools.gtm_actions.read_artifact",
        return_value={
            "review_status": "pending",
            "content": {
                "to": "user@example.com",
                "subject": "Hello",
                "body": "Hi",
            },
        },
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={
                    "to": "user@example.com",
                    "subject": "Hello",
                    "body": "Hi",
                    "artifact_id": "pitch_email-1",
                },
            ),
            context,
        )

    assert result.output["status"] == "error"
    assert result.output["real"] is False
    assert result.output["sent_messages"][0]["status"] == "error"
    assert result.output["sent_messages"][0]["artifact_id"] == "pitch_email-1"
    assert "not approved for send" in result.output["sent_messages"][0]["error"]


def test_gtm_email_send_uses_network_egress_for_real_send() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_send": {
            "secret_value": "token-123",
            "user": "me",
            "trusted_destination_hosts": ["gmail.googleapis.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/v1/users/me/messages/send",
        connect_url="https://1.2.3.4/v1/users/me/messages/send",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(status_code=200, headers={}, body_text='{"id":"msg-1"}', body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "user@example.com", "subject": "Hello", "body": "Hi"},
            ),
            context,
        )

    authority.request.assert_called_once()
    request_kwargs = authority.request.call_args.kwargs
    assert "/gmail/v1/users/me/messages/send" in request_kwargs["url"]
    assert "raw" in request_kwargs["json_body"]
    assert result.output["real"] is True
    assert result.output["provider"] == "gmail_api"
    assert result.output["provider_message_id"] == "msg-1"
    assert result.output["sent_messages"][0]["provider_message_id"] == "msg-1"
    assert "body" not in result.output["sent_messages"][0]


def test_gtm_email_send_uses_runtime_credential_material() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_send": RuntimeCredentialMaterial(
            reference=CredentialReference(
                credential_id="oauth-gmail",
                provider="external_email",
                credential_type="api_key",
            ),
            secret_value="token-123",
            trusted_destination_hosts=("gmail.googleapis.com",),
        )
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        connect_url="https://1.2.3.4/gmail/v1/users/me/messages/send",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(status_code=200, headers={}, body_text='{"id":"msg-1"}', body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "user@example.com", "subject": "Hello", "body": "Hi"},
            ),
            context,
        )

    assert result.output["real"] is True
    assert authority.request.call_args.kwargs["headers"]["Authorization"] == "Bearer token-123"


def test_gtm_email_check_uses_gmail_api_with_runtime_credential_material() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_check").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_check": RuntimeCredentialMaterial(
            reference=CredentialReference(
                credential_id="oauth-gmail",
                provider="external_email",
                credential_type="api_key",
            ),
            secret_value="token-123",
            trusted_destination_hosts=("gmail.googleapis.com",),
        )
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        connect_url="https://1.2.3.4/gmail/v1/users/me/messages",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"messages":[{"id":"m1","threadId":"t1","snippet":"Hello"}]}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_check",
                input={"query": "is:unread", "limit": 3},
            ),
            context,
        )

    assert result.output["emails"] == [{"id": "m1", "thread_id": "t1", "snippet": "Hello"}]
    assert result.output["real"] is True
    assert "is%3Aunread" in authority.request.call_args.kwargs["url"]


def test_gtm_email_check_fail_closed_on_credentialed_api_error() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_check").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_check": {
            "secret_value": "token-123",
            "trusted_destination_hosts": ["gmail.googleapis.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/gmail/v1/users/me/messages",
        connect_url="https://1.2.3.4/gmail/v1/users/me/messages",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(status_code=503, headers={}, body_text="unavailable", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        with pytest.raises(ValueError, match="credentialed path"):
            handler(
                ToolInvocation(
                    action="gtm.email_check",
                    input={"query": "is:unread", "limit": 3},
                ),
                context,
            )


def test_gtm_email_check_simulated_without_credential(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", "1")
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.email_check",
            input={"query": "is:unread", "limit": 2},
        ),
        _context(),
    )

    assert result.output["emails"][0]["id"] == "sim-1"
    assert result.side_effect_class.value == "external_read"


def test_gtm_email_send_rejects_non_2xx_response() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_send": {
            "secret_value": "token-123",
            "user": "me",
            "trusted_destination_hosts": ["gmail.googleapis.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/v1/users/me/messages/send",
        connect_url="https://1.2.3.4/v1/users/me/messages/send",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(status_code=500, headers={}, body_text="error", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "user@example.com", "subject": "Hello", "body": "Hi"},
            ),
            context,
        )

    assert result.output["real"] is False
    assert result.output["status"] == "error"
    assert "500" in result.output["error"]


def test_gtm_email_send_propagates_idempotency_key_to_provider() -> None:
    from backend.services.tools.action_registry import ActionRegistry
    from backend.services.tools.gtm_actions import register_gtm_actions

    registry = ActionRegistry()
    register_gtm_actions(registry)
    handler = registry.get("gtm.email_send").handler
    context = _context()
    context.runtime_credentials = {
        "gtm.email_send": {
            "secret_value": "token-123",
            "user": "me",
            "trusted_destination_hosts": ["gmail.googleapis.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://gmail.googleapis.com/v1/users/me/messages/send",
        connect_url="https://1.2.3.4/v1/users/me/messages/send",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="gmail.googleapis.com",
        host_header="gmail.googleapis.com",
    )
    response = NetworkEgressResponse(status_code=200, headers={}, body_text='{"id":"msg-1"}', body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.gtm_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="gtm.email_send",
                input={"to": "user@example.com", "subject": "Hello", "body": "Hi"},
                idempotency_key="idem-gmail-1",
            ),
            context,
        )

    assert authority.request.call_args.kwargs["headers"]["Idempotency-Key"] == "idem-gmail-1"
    assert result.output["idempotency_key"] == "idem-gmail-1"
    assert result.output["sent_messages"][0]["idempotency_key"] == "idem-gmail-1"


@patch("backend.services.light_crm.workflow.complete_internal_crm_upsert")
def test_gtm_crm_upsert_simulated_without_credential(mock_complete: MagicMock) -> None:
    session = MagicMock()
    mock_complete.return_value = {"id": "contact-1", "email": "lead@example.com"}
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
        session_factory=lambda: session,
    )
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.crm_upsert",
            input={"record_type": "lead", "data": {"email": "lead@example.com"}},
        ),
        context,
    )

    assert result.output.get("real") is True
    assert result.output["status"] == "upserted_internal"
    assert result.output["source"] == "ajenda_brain"
    assert result.side_effect_class.value == "internal_write"
    mock_complete.assert_called_once()
