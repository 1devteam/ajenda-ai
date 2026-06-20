from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

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
    assert result.side_effect_class.value == "external_send"


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
    assert "is%3Aunread" in authority.request.call_args.kwargs["url"]


def test_gtm_crm_upsert_simulated_without_credential() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="gtm.crm_upsert",
            input={"record_type": "lead", "data": {"email": "lead@example.com"}},
        ),
        _context(),
    )

    assert result.output.get("real") is not True
    assert result.side_effect_class.value == "external_write"
