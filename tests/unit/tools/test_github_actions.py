from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.github_actions import register_github_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_github_repo_read_simulated_without_credential() -> None:
    registry = ActionRegistry()
    register_github_actions(registry)
    result = registry.invoke(
        ToolInvocation(action="github.repo_read", input={"owner": "ajenda", "repo": "ajenda-ai"}),
        _context(),
    )

    assert result.output["real"] is False
    assert result.output["repository"]["full_name"] == "ajenda/ajenda-ai"
    assert result.side_effect_class.value == "external_read"


def test_github_repo_read_uses_api_with_runtime_credential() -> None:
    registry = ActionRegistry()
    register_github_actions(registry)
    handler = registry.get("github.repo_read").handler
    context = _context()
    context.runtime_credentials = {
        "github.repo_read": {
            "secret_value": "github-token",
            "trusted_destination_hosts": ["api.github.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://api.github.com/repos/ajenda/ajenda-ai",
        connect_url="https://1.2.3.4/repos/ajenda/ajenda-ai",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.github.com",
        host_header="api.github.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"id":42,"full_name":"ajenda/ajenda-ai","private":false}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.github_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(action="github.repo_read", input={"owner": "ajenda", "repo": "ajenda-ai"}),
            context,
        )

    assert result.output["real"] is True
    assert result.output["repository"]["id"] == 42
    assert authority.request.call_args.kwargs["headers"]["Authorization"] == "Bearer github-token"


def test_github_repo_read_fail_closed_when_response_body_truncated() -> None:
    registry = ActionRegistry()
    register_github_actions(registry)
    handler = registry.get("github.repo_read").handler
    context = _context()
    context.runtime_credentials = {
        "github.repo_read": {
            "secret_value": "github-token",
            "trusted_destination_hosts": ["api.github.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://api.github.com/repos/ajenda/ajenda-ai",
        connect_url="https://1.2.3.4/repos/ajenda/ajenda-ai",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.github.com",
        host_header="api.github.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"id":42,"full_name":"ajenda/ajenda-ai"',
        body_truncated=True,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.github_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        try:
            handler(
                ToolInvocation(action="github.repo_read", input={"owner": "ajenda", "repo": "ajenda-ai"}),
                context,
            )
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "truncated" in str(exc)


def test_github_repo_read_fail_closed_on_credentialed_api_error() -> None:
    registry = ActionRegistry()
    register_github_actions(registry)
    handler = registry.get("github.repo_read").handler
    context = _context()
    context.runtime_credentials = {
        "github.repo_read": {
            "secret_value": "github-token",
            "trusted_destination_hosts": ["api.github.com"],
        }
    }
    authority = MagicMock()
    authority.request.side_effect = RuntimeError("egress blocked")

    with patch(
        "backend.services.tools.github_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        try:
            handler(
                ToolInvocation(action="github.repo_read", input={"owner": "ajenda", "repo": "ajenda-ai"}),
                context,
            )
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "credentialed path" in str(exc)