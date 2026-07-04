from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
from backend.services.plugins.crm_client import StandardCrmClient, is_live_external_crm_result
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-1",
        task_id=__import__("uuid").uuid4(),
        mission_id=__import__("uuid").uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_is_live_external_crm_result_recognizes_hubspot_adapter_source() -> None:
    assert is_live_external_crm_result(source="hubspot", real=True) is True
    assert is_live_external_crm_result(source="external_crm", real=True) is True
    assert is_live_external_crm_result(source="ajenda_brain", real=True) is False
    assert is_live_external_crm_result(source="hubspot", real=True, error="timeout") is False


def test_crm_search_uses_internal_brain_without_credential() -> None:
    result = StandardCrmClient().search(
        context=_context(),
        company="Acme",
        domain="acme.com",
        credential=None,
    )
    assert result.real is True
    assert result.source == "ajenda_brain"


@patch("backend.services.light_crm.workflow.complete_internal_crm_upsert")
def test_crm_upsert_writes_internal_record_without_credential(mock_complete: MagicMock) -> None:
    session = MagicMock()
    mock_complete.return_value = {"id": "contact-1", "email": "buyer@example.com", "name": "Buyer"}
    context = ActionRuntimeContext(
        tenant_id="tenant-1",
        task_id=__import__("uuid").uuid4(),
        mission_id=__import__("uuid").uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=lambda: session,
    )
    result = StandardCrmClient().upsert(
        context=context,
        record_type="lead",
        data={"email": "buyer@example.com", "name": "Buyer"},
        credential=None,
    )
    assert result.real is True
    assert result.status == "upserted_internal"
    assert result.source == "ajenda_brain"
    assert result.record_id == "contact-1"
    mock_complete.assert_called_once()


def test_crm_search_calls_external_adapter_with_credential() -> None:
    destination = VettedNetworkDestination(
        original_url="https://crm.example.com/v1/search",
        connect_url="https://10.0.0.1/v1/search",
        pinned_ip=__import__("ipaddress").ip_address("10.0.0.1"),
        sni_hostname="crm.example.com",
        host_header="crm.example.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"results":[{"id":"1"}],"count":1,"source":"hubspot"}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)
    credential = {
        "secret_value": "pak-token",
        "trusted_destination_hosts": ["crm.example.com"],
    }

    with patch(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        return_value=authority,
    ):
        result = StandardCrmClient().search(
            context=_context(),
            company="Acme",
            domain="acme.com",
            credential=credential,
            invocation=ToolInvocation(action="sales.research", input={"lead": {}}),
        )

    assert result.real is True
    assert result.source == "hubspot"
    assert authority.request.called
    assert "company=Acme" in authority.request.call_args.kwargs["url"]
    assert " " not in authority.request.call_args.kwargs["url"].split("?", 1)[-1]


def test_crm_search_url_encodes_company_names_with_spaces() -> None:
    destination = VettedNetworkDestination(
        original_url="https://crm.example.com/v1/search",
        connect_url="https://10.0.0.1/v1/search",
        pinned_ip=__import__("ipaddress").ip_address("10.0.0.1"),
        sni_hostname="crm.example.com",
        host_header="crm.example.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text='{"results":[],"count":0,"source":"hubspot"}',
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)
    credential = {
        "secret_value": "pak-token",
        "trusted_destination_hosts": ["crm.example.com"],
    }

    with patch(
        "backend.services.plugins.crm_client.get_default_network_egress_authority",
        return_value=authority,
    ):
        StandardCrmClient().search(
            context=_context(),
            company="PRIDE Proof Co",
            domain="",
            credential=credential,
        )

    assert "company=PRIDE+Proof+Co" in authority.request.call_args.kwargs["url"]
