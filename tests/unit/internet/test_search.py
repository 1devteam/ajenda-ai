from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from backend.services.internet.contracts import SearchBundle, SearchHit
from backend.services.internet.modes import InternetAccessMode, is_reserved_mode, is_shipped_mode
from backend.services.internet.search import (
    DuckDuckGoHtmlSearchProvider,
    DuckDuckGoInstantAnswerProvider,
    public_search,
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


def test_governed_html_search_parses_general_result_links_and_uses_egress() -> None:
    destination = VettedNetworkDestination(
        original_url="https://html.duckduckgo.com/html/?q=hvac",
        connect_url="https://1.2.3.4/html/?q=hvac",
        pinned_ip=__import__("ipaddress").ip_address("1.2.3.4"),
        sni_hostname="html.duckduckgo.com",
        host_header="html.duckduckgo.com",
    )
    response = NetworkEgressResponse(
        status_code=200,
        headers={"content-type": "text/html"},
        body_text=(
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example HVAC</a>'
            '<a class="result__snippet">Dallas heating and cooling</a>'
        ),
        body_truncated=False,
    )
    authority = MagicMock()
    authority.request.return_value = (destination, response)

    with patch("backend.services.internet.search.get_default_network_egress_authority", return_value=authority):
        bundle = public_search(
            query="Dallas HVAC companies",
            limit=3,
            timeout_seconds=10.0,
            provider=DuckDuckGoHtmlSearchProvider(),
        )

    assert bundle.provider == "duckduckgo_html"
    assert bundle.real is True
    assert [(item.title, item.url) for item in bundle.results] == [("Example HVAC", "https://example.com")]
    assert bundle.attempts[0].outcome == "results"
    assert authority.request.call_args.kwargs["allowed_hosts"] == ["html.duckduckgo.com"]


def test_fallback_preserves_the_failed_provider_attempt(monkeypatch) -> None:
    class FailingProvider:
        name = "first"

        def search(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SearchBundle(provider=self.name, real=False, error="HTTP 429", status_code=429)

    class WorkingProvider:
        name = "second"

        def search(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SearchBundle(
                provider=self.name,
                real=True,
                results=(SearchHit(title="Example", snippet="", url="https://example.com"),),
            )

    monkeypatch.setattr(
        "backend.services.internet.search.resolve_public_search_provider_chain",
        lambda: [FailingProvider(), WorkingProvider()],
    )

    bundle = public_search(query="example", limit=2)

    assert bundle.provider == "second"
    assert [attempt.outcome for attempt in bundle.attempts] == ["failure", "results"]
    assert bundle.attempts[0].status_code == 429


def test_valid_empty_search_is_not_reported_as_a_provider_error(monkeypatch) -> None:
    class FailedProvider:
        name = "first"

        def search(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SearchBundle(provider=self.name, real=False, error="HTTP 429", status_code=429)

    class EmptyProvider:
        name = "second"

        def search(self, **_kwargs):  # type: ignore[no-untyped-def]
            return SearchBundle(provider=self.name, real=True)

    monkeypatch.setattr(
        "backend.services.internet.search.resolve_public_search_provider_chain",
        lambda: [FailedProvider(), EmptyProvider()],
    )

    bundle = public_search(query="no matching companies", limit=2)

    assert bundle.provider == "second"
    assert bundle.real is True
    assert bundle.results == ()
    assert bundle.error is None
    assert [(attempt.provider, attempt.outcome, attempt.error) for attempt in bundle.attempts] == [
        ("first", "failure", "HTTP 429"),
        ("second", "empty", None),
    ]
