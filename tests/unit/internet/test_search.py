from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.services.internet.modes import InternetAccessMode, is_reserved_mode, is_shipped_mode
from backend.services.internet.search import DuckDuckGoInstantAnswerProvider, public_search
from backend.services.network_egress import NetworkEgressResponse, VettedNetworkDestination


def test_modes_mark_browser_and_open_write_reserved() -> None:
    assert is_shipped_mode(InternetAccessMode.PUBLIC_SEARCH)
    assert is_shipped_mode(InternetAccessMode.PAGE_READ)
    assert is_shipped_mode(InternetAccessMode.HTTP_REQUEST)
    assert is_reserved_mode(InternetAccessMode.BROWSER_SESSION)
    assert is_reserved_mode(InternetAccessMode.OPEN_WRITE)


def test_public_search_parses_ddg_payload() -> None:
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
        "backend.services.internet.search.get_default_network_egress_authority",
        return_value=authority,
    ):
        bundle = public_search(
            query="HubSpot CRM",
            limit=5,
            timeout_seconds=10.0,
            provider=DuckDuckGoInstantAnswerProvider(),
        )

    assert bundle.real is True
    assert bundle.access_mode == InternetAccessMode.PUBLIC_SEARCH
    assert len(bundle.results) >= 3
