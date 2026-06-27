from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.tools.action_registry import ActionRegistry
from backend.services.tools.salesforce_actions import register_salesforce_actions
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_salesforce_soql_read_simulated_without_credential() -> None:
    registry = ActionRegistry()
    register_salesforce_actions(registry)
    result = registry.invoke(
        ToolInvocation(
            action="salesforce.soql_read",
            input={"soql": "SELECT Id, Name FROM Account LIMIT 1"},
        ),
        _context(),
    )

    assert result.output["real"] is False
    assert result.output["result"]["records"][0]["Id"] == "sim-sf-1"


def test_salesforce_soql_read_rejects_mutating_query() -> None:
    from backend.services.tools.salesforce_actions import SalesforceSoqlReadInput

    with pytest.raises(ValueError, match="read-only SELECT"):
        SalesforceSoqlReadInput.model_validate({"soql": "DELETE FROM Account"})


def test_salesforce_soql_read_uses_api_with_runtime_credential() -> None:
    registry = ActionRegistry()
    register_salesforce_actions(registry)
    handler = registry.get("salesforce.soql_read").handler
    context = _context()
    context.runtime_credentials = {
        "salesforce.soql_read": {
            "secret_value": "sf-token",
            "trusted_destination_hosts": ["acme.my.salesforce.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://acme.my.salesforce.com/services/data/v59.0/query",
        connect_url="https://1.2.3.5/services/data/v59.0/query",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.5"),
        sni_hostname="acme.my.salesforce.com",
        host_header="acme.my.salesforce.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"totalSize":1,"done":true,"records":[{"Id":"001","Name":"Acme"}]}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.salesforce_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = handler(
            ToolInvocation(
                action="salesforce.soql_read",
                input={"soql": "SELECT Id, Name FROM Account LIMIT 1"},
            ),
            context,
        )

    assert result.output["real"] is True
    assert result.output["result"]["records"][0]["Id"] == "001"
    assert "acme.my.salesforce.com" in authority.request.call_args.kwargs["url"]


def test_salesforce_soql_read_fail_closed_on_credentialed_api_error() -> None:
    registry = ActionRegistry()
    register_salesforce_actions(registry)
    handler = registry.get("salesforce.soql_read").handler
    context = _context()
    context.runtime_credentials = {
        "salesforce.soql_read": {
            "secret_value": "sf-token",
            "trusted_destination_hosts": ["acme.my.salesforce.com"],
        }
    }
    destination = VettedNetworkDestination(
        original_url="https://acme.my.salesforce.com/services/data/v59.0/query",
        connect_url="https://1.2.3.5/services/data/v59.0/query",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.5"),
        sni_hostname="acme.my.salesforce.com",
        host_header="acme.my.salesforce.com",
    )
    response = NetworkEgressResponse(status_code=401, headers={}, body_text="unauthorized", body_truncated=False)
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.salesforce_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        with pytest.raises(ValueError, match="credentialed path"):
            handler(
                ToolInvocation(
                    action="salesforce.soql_read",
                    input={"soql": "SELECT Id FROM Account LIMIT 1"},
                ),
                context,
            )