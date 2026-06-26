from __future__ import annotations

from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-standalone",
        task_id=__import__("uuid").uuid4(),
        mission_id=__import__("uuid").uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_web_research_runs_without_external_plugins() -> None:
    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "Acme Manufacturing", "company": "Acme Manufacturing"},
        ),
        _context(),
    )
    assert result.provider == "ajenda_brain"
    assert result.output["real"] is True
    assert result.output["plugin_required"] is False
    assert result.side_effect_class.value == "internal_read"


def test_fetch_duckduckgo_parses_nested_related_topics() -> None:
    import json
    from unittest.mock import MagicMock, patch

    from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination
    from backend.services.tools.standalone_actions import _fetch_duckduckgo_instant_answer

    destination = VettedNetworkDestination(
        original_url="https://api.duckduckgo.com/",
        connect_url="https://1.2.3.4/",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="api.duckduckgo.com",
        host_header="api.duckduckgo.com",
    )
    body = {
        "Heading": "HubSpot",
        "AbstractText": "HubSpot is a CRM platform.",
        "AbstractURL": "https://hubspot.com",
        "Results": [{"Text": "HubSpot CRM - Official site", "FirstURL": "https://hubspot.com/crm"}],
        "RelatedTopics": [
            {
                "Name": "Products",
                "Topics": [{"Text": "Marketing Hub - Inbound tools", "FirstURL": "https://hubspot.com/marketing"}],
            }
        ],
    }
    response = NetworkEgressResponse(
        status_code=200,
        headers={},
        body_text=json.dumps(body),
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.tools.standalone_actions.get_default_network_egress_authority",
        return_value=authority,
    ):
        bundle = _fetch_duckduckgo_instant_answer(query="HubSpot CRM", limit=5, timeout_seconds=10.0)

    assert bundle["real"] is True
    assert bundle["result_count"] >= 3


def test_web_search_merges_internal_records_and_public_results(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    monkeypatch.setattr(
        standalone_actions,
        "_fetch_duckduckgo_instant_answer",
        lambda **kwargs: {
            "provider": "duckduckgo_instant_answer",
            "real": True,
            "results": [{"title": "Acme", "snippet": "Acme builds robots", "url": "https://acme.example"}],
        },
    )

    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(action="web.search", input={"query": "Acme robotics", "limit": 3}),
        _context(),
    )
    assert result.action == "web.search"
    assert result.output["search_real"] is True
    assert result.output["web_result_count"] == 1
    assert result.side_effect_class.value == "external_read"
