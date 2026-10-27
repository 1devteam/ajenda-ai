from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.services.internet.modes import InternetAccessMode, is_reserved_mode, is_shipped_mode
from backend.services.internet.search import (
    DuckDuckGoHtmlSearchProvider,
    DuckDuckGoInstantAnswerProvider,
    public_search,
    resolve_public_search_provider_chain,
)
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
    assert [item.provider for item in bundle.attempts] == ["duckduckgo_instant_answer"]


def test_governed_html_search_parses_general_result_rows() -> None:
    destination = VettedNetworkDestination(
        original_url="https://html.duckduckgo.com/html/?q=HVAC",
        connect_url="https://1.2.3.4/html/?q=HVAC",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="html.duckduckgo.com",
        host_header="html.duckduckgo.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body_text=(
            '<a class="result__a" href="https://acme-hvac.example/">Acme HVAC</a>'
            '<a class="result__snippet">Commercial HVAC service in Dallas.</a>'
            '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fbeta-hvac.example%2F">Beta HVAC</a>'
            '<div class="result__snippet">Heating and cooling.</div>'
        ),
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch(
        "backend.services.internet.search.get_default_network_egress_authority",
        return_value=authority,
    ):
        bundle = public_search(
            query="HVAC companies in Dallas",
            limit=5,
            timeout_seconds=10.0,
            provider=DuckDuckGoHtmlSearchProvider(),
        )

    assert bundle.provider == "duckduckgo_html"
    assert bundle.real is True
    assert [(item.title, item.url) for item in bundle.results] == [
        ("Acme HVAC", "https://acme-hvac.example/"),
        ("Beta HVAC", "https://beta-hvac.example/"),
    ]
    assert [item.provider for item in bundle.attempts] == ["duckduckgo_html"]
    authority.request.assert_called_once()


def test_runtime_provider_chain_never_selects_package_owned_ddgs_transport() -> None:
    assert [provider.name for provider in resolve_public_search_provider_chain(preferred="auto")] == [
        "duckduckgo_html",
        "duckduckgo_instant_answer",
    ]
    assert [provider.name for provider in resolve_public_search_provider_chain(preferred="ddgs")] == [
        "duckduckgo_html",
        "duckduckgo_instant_answer",
    ]
