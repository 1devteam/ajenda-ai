from __future__ import annotations

from unittest.mock import patch

from backend.services.internet.contracts import PageSnapshot
from backend.services.internet.modes import InternetAccessMode
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-web",
        task_id=__import__("uuid").uuid4(),
        mission_id=__import__("uuid").uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
    )


def test_web_page_read_action_returns_external_read_evidence() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/",
        real=True,
        status_code=200,
        title="Example Domain",
        text_preview="Example Domain content",
        body_preview="<html>",
        access_mode=InternetAccessMode.PAGE_READ,
        browser_ready=False,
    )
    with patch("backend.services.tools.web_actions.fetch_public_page", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(action="web.page_read", input={"url": "https://example.com"}),
            _context(),
        )
    assert result.action == "web.page_read"
    assert result.provider == "ajenda_internet"
    assert result.side_effect_class.value == "external_read"
    assert result.output["real"] is True
    assert result.output["title"] == "Example Domain"
    assert result.output["browser_ready"] is False
    assert "web.browser_session" in result.output["related_modes"]["browser_session"]
    assert result.evidence[0].action_name == "web.page_read"


def test_web_browser_session_and_open_write_registered() -> None:
    registry = get_default_action_registry(rebuild=True)
    assert "web.browser_session" in registry.actions or registry.get("web.browser_session")
    assert registry.get("web.open_write").side_effect_class.value == "external_write"


def test_web_page_read_failure_is_not_fake_success() -> None:
    snapshot = PageSnapshot(
        url="https://blocked.invalid/",
        real=False,
        error="web.page_read DNS resolution failed",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    with patch("backend.services.tools.web_actions.fetch_public_page", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(action="web.page_read", input={"url": "https://blocked.invalid"}),
            _context(),
        )
    assert result.output["real"] is False
    assert result.output["error"]


def test_observe_contacts_marks_matching_site_verified_and_directory_unverified() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    matching = PageSnapshot(
        url="https://acmehvac.example/",
        real=True,
        status_code=200,
        title="Acme HVAC | Heating and cooling",
        text_preview="Contact Acme HVAC at service@acmehvac.example",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    directory = PageSnapshot(
        url="https://directory.example/listing/acme-hvac",
        real=True,
        status_code=200,
        title="Top HVAC companies",
        text_preview="Acme HVAC 555-555-5555",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "Acme HVAC",
                    "domain": "acmehvac.example",
                    "url": matching.url,
                    "website": matching.url,
                    "product_description": "Residential heating and cooling services.",
                    "research_summary": "Acme HVAC provides heating and cooling services.",
                    "sources": [matching.url],
                },
                {"company": "Acme HVAC Directory", "domain": "directory.example", "url": directory.url},
            ],
            "requested_quantity": 2,
            "binding_required": True,
        },
    )
    with patch(
        "backend.services.tools.web_actions.fetch_public_page",
        side_effect=[matching, directory],
    ):
        result = research_observe_contacts(invocation, _context())

    candidates = {item["company"]: item for item in result.output["prospect_candidates"]}
    assert candidates["Acme HVAC"]["identity_status"] == "verified"
    assert candidates["Acme HVAC Directory"]["identity_status"] == "unverified"
    observed = result.output["observed_contacts"][0]
    assert observed["identity_status"] == "verified"
    assert observed["website"] == matching.url
    assert observed["product_description"] == "Residential heating and cooling services."
    assert observed["research_summary"] == "Acme HVAC provides heating and cooling services."
    assert observed["sources"] == [matching.url]
    assert all(item.get("company") != "Acme HVAC Directory" for item in result.output["observed_contacts"])
    assert any(item.get("reason") == "identity_unverified" for item in result.output["unobserved"])


def test_observe_contacts_promotes_external_directory_links_after_verification() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    directory = PageSnapshot(
        url="https://directory.example/hvac",
        real=True,
        status_code=200,
        title="Top HVAC companies",
        text_preview="Local HVAC providers",
        body_preview="",
        extraction={"links": [{"url": "https://acmehvac.example/", "text": "Acme HVAC"}]},
        access_mode=InternetAccessMode.PAGE_READ,
    )
    official = PageSnapshot(
        url="https://acmehvac.example/",
        real=True,
        status_code=200,
        title="Acme HVAC",
        text_preview="Acme HVAC serves Dallas homeowners. service@acmehvac.example",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [{"company": "Top HVAC companies", "domain": "directory.example", "url": directory.url}],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_actions.fetch_public_page", side_effect=[directory, official]):
        result = research_observe_contacts(invocation, _context())

    promoted = result.output["verified_prospect_candidates"]
    assert len(promoted) == 1
    assert promoted[0]["company"] == "Acme HVAC"
    assert promoted[0]["prospect_id"] == "web:resolved:acmehvac.example"
    assert promoted[0]["identity_status"] == "verified"
    assert promoted[0]["identity_evidence_urls"] == [directory.url, official.url]
    assert result.output["observed_contacts"][0]["website"] == official.url


def test_observe_contacts_does_not_treat_known_listing_host_as_official() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    listing = PageSnapshot(
        url="https://www.bestprosintown.com/tx/dallas/hvac/",
        real=True,
        status_code=200,
        title="Best HVAC companies in Dallas",
        text_preview="Airtron Heating and Air Conditioning",
        body_preview="",
        extraction={"links": []},
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "Best HVAC companies in Dallas",
                    "domain": "bestprosintown.com",
                    "url": listing.url,
                }
            ],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_actions.fetch_public_page", return_value=listing):
        result = research_observe_contacts(invocation, _context())

    assert result.output["prospect_candidates"][0]["identity_status"] == "unverified"
    assert result.output["observed_contacts"] == []
