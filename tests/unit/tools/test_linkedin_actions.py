from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.linkedin_actions import register_linkedin_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_linkedin_profile_read_simulated_without_credential(monkeypatch) -> None:
    monkeypatch.setenv("AJENDA_ALLOW_SIMULATED_EXTERNAL", "1")
    registry = ActionRegistry()
    register_linkedin_actions(registry)
    result = registry.invoke(
        ToolInvocation(action="linkedin.profile_read", input={}),
        _context(),
    )

    assert result.output["real"] is False
    assert result.output["profile"]["id"] == "sim-linkedin-1"
    assert result.side_effect_class.value == "external_read"


def test_linkedin_profile_read_uses_api_with_runtime_credential() -> None:
    registry = ActionRegistry()
    register_linkedin_actions(registry)
    handler = registry.get("linkedin.profile_read").handler
    context = _context()
    context.runtime_credentials = {
        "linkedin.profile_read": {
            "secret_value": "linkedin-token",
            "trusted_destination_hosts": ["api.linkedin.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://api.linkedin.com/v2/me",
        connect_url="https://1.2.3.4/v2/me",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.linkedin.com",
        host_header="api.linkedin.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"id":"live-profile","firstName":{"localized":{"en_US":"Jane"}}}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.linkedin_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(ToolInvocation(action="linkedin.profile_read", input={}), context)

    assert result.output["real"] is True
    assert result.output["profile"]["id"] == "live-profile"
    assert authority.request.call_args.kwargs["headers"]["Authorization"] == "Bearer linkedin-token"


def test_linkedin_profile_read_fail_closed_on_credentialed_api_error() -> None:
    registry = ActionRegistry()
    register_linkedin_actions(registry)
    handler = registry.get("linkedin.profile_read").handler
    context = _context()
    context.runtime_credentials = {
        "linkedin.profile_read": {
            "secret_value": "linkedin-token",
            "trusted_destination_hosts": ["api.linkedin.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://api.linkedin.com/v2/me",
        connect_url="https://1.2.3.4/v2/me",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.linkedin.com",
        host_header="api.linkedin.com",
    )
    response = NetworkEgressResponse(status_code=401, headers={}, body_text="unauthorized", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.linkedin_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        with pytest.raises(ValueError, match="credentialed path"):
            handler(ToolInvocation(action="linkedin.profile_read", input={}), context)
