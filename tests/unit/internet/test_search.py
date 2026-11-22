from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

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


def _search_page(body: str, *, status: int = 200) -> NetworkEgressResponse:
    return NetworkEgressResponse(status_code=status, headers={}, body_text=body, body_truncated=False)


def _next_search_page(action: str = "/html/", *, offset: int = 10) -> str:
    return (
        f'<form method="post" action="{action}">'
        '<input type="hidden" name="q" value="Austin software">'
        f'<input type="hidden" name="s" value="{offset}">'
        '<input type="hidden" name="vqd" value="returned-token">'
        '<input type="hidden" name="unexpected" value="drop-me">'
        '<input type="submit" value="Next"></form>'
    )


def test_html_search_reserves_space_for_later_organic_results() -> None:
    authority = MagicMock()
    authority.request.side_effect = [
        (
            None,
            _search_page(
                '<div class="result result--ad"><div><a class="result__a" href="https://ads.example/">Ad</a>'
                '<a class="result__snippet">Ad snippet</a></div></div>'
                '<a class="result__a" href="//duckduckgo.com/y.js?param=ad">Ad redirect</a>'
                '<a class="result__snippet">Another ad snippet</a>'
                '<a class="result__a" href="https://first.example/">First</a>'
                '<a class="result__a" href="https://second.example/">Second</a>'
                '<div class="result__snippet"><div>Second snippet</div> and more</div>' + _next_search_page()
            ),
        ),
        (
            None,
            _search_page(
                '<a class="result__a" href="https://first.example/">Duplicate</a>'
                '<a class="result__a" href="https://later.example/">Later organic hit</a>'
            ),
        ),
    ]

    with patch("backend.services.internet.search.get_default_network_egress_authority", return_value=authority):
        bundle = public_search(
            query="Austin software", limit=2, timeout_seconds=8, provider=DuckDuckGoHtmlSearchProvider()
        )

    assert [(hit.title, hit.snippet) for hit in bundle.results] == [("First", ""), ("Later organic hit", "")]
    assert bundle.attempts[0].pages_fetched == 2
    assert bundle.attempts[0].sponsored_rows_skipped == 2
    first, second = (call.kwargs for call in authority.request.call_args_list)
    assert parse_qs(urlparse(first["url"]).query) == {"q": ["Austin software"], "k1": ["-1"], "kav": ["1"]}
    assert second["url"] == "https://html.duckduckgo.com/html/"
    assert second["method"] == "POST"
    assert second["allowed_hosts"] == ["html.duckduckgo.com"]
    assert second["action_name"] == "web.search"
    assert parse_qs(second["content"].decode()) == {
        "q": ["Austin software"],
        "s": ["10"],
        "vqd": ["returned-token"],
        "k1": ["-1"],
        "kav": ["1"],
    }


@pytest.mark.parametrize("action", ["https://other.example/html/", "/redirect", "/html/?unexpected=1"])
def test_html_search_does_not_follow_an_unexpected_continuation_target(action: str) -> None:
    authority = MagicMock()
    authority.request.return_value = (None, _search_page(_next_search_page(action)))

    with patch("backend.services.internet.search.get_default_network_egress_authority", return_value=authority):
        bundle = public_search(query="Austin software", limit=9, provider=DuckDuckGoHtmlSearchProvider())

    assert bundle.real
    assert bundle.results == ()
    assert bundle.attempts[0].pages_fetched == 1
    assert authority.request.call_count == 1


def test_html_search_keeps_first_page_evidence_when_continuation_fails() -> None:
    authority = MagicMock()
    authority.request.side_effect = [
        (
            None,
            _search_page('<a class="result__a" href="https://example.com/">Example</a>' + _next_search_page()),
        ),
        (None, _search_page("", status=429)),
    ]

    with patch("backend.services.internet.search.get_default_network_egress_authority", return_value=authority):
        bundle = public_search(query="Austin software", limit=9, provider=DuckDuckGoHtmlSearchProvider())

    assert bundle.real
    assert [hit.url for hit in bundle.results] == ["https://example.com/"]
    assert bundle.attempts[0].pages_fetched == 1
    assert bundle.error == "HTTP 429"
    assert authority.request.call_count == 2


def test_html_search_bounds_pages_and_preserves_snippet_ownership() -> None:
    authority = MagicMock()
    authority.request.side_effect = [
        (
            None,
            _search_page(
                '<div class="result"><a class="result__a" href="https://example.com/">Example</a>'
                '<div class="result__snippet"><div>Nested</div> snippet</div></div>' + _next_search_page(offset=offset)
            ),
        )
        for offset in (10, 25, 40)
    ]

    with patch("backend.services.internet.search.get_default_network_egress_authority", return_value=authority):
        bundle = public_search(query="Austin software", limit=9, provider=DuckDuckGoHtmlSearchProvider())

    assert [(hit.url, hit.snippet) for hit in bundle.results] == [("https://example.com/", "Nested snippet")]
    assert bundle.attempts[0].pages_fetched == 3
    assert authority.request.call_count == 3


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
