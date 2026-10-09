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
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=snapshot):
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


def test_web_browser_session_emits_typed_page_observation_artifact() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/",
        real=True,
        status_code=200,
        title="Example Domain",
        text_preview="Example Domain content",
        body_preview="Example Domain content",
        access_mode=InternetAccessMode.BROWSER_SESSION,
        browser_ready=True,
        extraction={
            "steps": [{"action": "navigate", "status_code": 200}],
            "observation_requirements": [{"kind": "title", "satisfied": True}],
            "observation_timestamp": "2026-09-21T00:00:00Z",
            "observation_satisfied": True,
            "blocked_samples": [],
            "request_vetting": "per_request",
            "dns_pin": "chromium_host_resolver_rules",
            "dns_pinned_hosts": ["example.com"],
            "allowed_hosts": ["example.com"],
            "engine": "chromium",
            "ephemeral_context": True,
        },
    )
    with patch("backend.services.tools.web_actions.run_browser_session", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(
                action="web.browser_session",
                input={
                    "url": "https://example.com",
                    "observation_requirements": [{"kind": "title"}],
                },
            ),
            _context(),
        )
    artifact = result.output["web_page_observation"]
    assert artifact["source_url"] == "https://example.com"
    assert artifact["final_url"] == "https://example.com/"
    assert artifact["observation_satisfied"] is True
    assert artifact["browser_trace"]
    assert artifact["network_provenance"]["dns_pin"] == "chromium_host_resolver_rules"
    assert result.evidence[0].structured_payload["network_provenance"] == artifact["network_provenance"]


def test_web_browser_session_preserves_runtime_error_in_failed_artifact() -> None:
    snapshot = PageSnapshot(
        url="https://example.com/",
        real=False,
        error="web.browser_session click step failed",
        access_mode=InternetAccessMode.BROWSER_SESSION,
        browser_ready=True,
    )
    with patch("backend.services.tools.web_actions.run_browser_session", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(
                action="web.browser_session",
                input={"url": "https://example.com", "observation_requirements": [{"kind": "title"}]},
            ),
            _context(),
        )
    assert result.output["web_page_observation"]["error"] == "web.browser_session click step failed"


def test_public_identity_verification_requires_company_industry_and_location_evidence() -> None:
    snapshot = PageSnapshot(
        url="https://acmehvac.example/",
        real=True,
        status_code=200,
        title="Acme HVAC",
        text_preview="Acme HVAC provides HVAC heating and cooling services in Dallas, Texas.",
        body_preview="",
        access_mode=InternetAccessMode.BROWSER_SESSION,
        browser_ready=True,
        extraction={
            "steps": [{"action": "navigate", "status_code": 200}],
            "observation_requirements": [
                {"kind": "title", "value": "Acme HVAC", "satisfied": True},
                {
                    "kind": "body",
                    "value": "Acme HVAC provides HVAC heating and cooling services in Dallas, Texas.",
                    "satisfied": True,
                },
            ],
            "observation_timestamp": "2026-09-23T00:00:00Z",
            "blocked_samples": [],
        },
    )
    with patch("backend.services.tools.web_actions.run_browser_session", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(
                action="research.verify_public_identity",
                input={
                    "url": "https://acmehvac.example",
                    "expected_company": "Acme HVAC",
                    "industry": "HVAC",
                    "location": "Dallas",
                },
            ),
            _context(),
        )
    artifact = result.output["public_identity_observation"]
    assert artifact["identity_status"] == "verified"
    assert artifact["identity_evidence_urls"] == ["https://acmehvac.example/"]
    assert artifact["final_url"] == "https://acmehvac.example/"
    assert artifact["title"] == "Acme HVAC"
    evidence_by_criterion = {item["criterion"]: item for item in artifact["identity_match_evidence"]}
    assert evidence_by_criterion["company_name_or_domain"]["matched"] is True
    assert evidence_by_criterion["company_name_or_domain"]["match_basis"] == "company_phrase"
    assert evidence_by_criterion["company_name_or_domain"]["observed_excerpt"]
    assert evidence_by_criterion["industry"]["observed_excerpt"]
    assert evidence_by_criterion["location"]["observed_excerpt"]


def test_public_identity_verification_fails_closed_for_missing_evidence() -> None:
    snapshot = PageSnapshot(
        url="https://directory.example/",
        real=True,
        status_code=200,
        title="Top HVAC Companies",
        text_preview="Top HVAC companies in Dallas",
        access_mode=InternetAccessMode.BROWSER_SESSION,
        browser_ready=True,
        extraction={"observation_requirements": [], "blocked_samples": []},
    )
    with patch("backend.services.tools.web_actions.run_browser_session", return_value=snapshot):
        registry = get_default_action_registry(rebuild=True)
        result = registry.invoke(
            ToolInvocation(
                action="research.verify_public_identity",
                input={
                    "url": "https://directory.example",
                    "expected_company": "Acme HVAC",
                    "industry": "HVAC",
                    "location": "Dallas",
                },
            ),
            _context(),
        )
    artifact = result.output["public_identity_observation"]
    assert artifact["identity_status"] == "unverified"
    assert "directory_or_third_party_page" in artifact["identity_gaps"]


def test_web_page_read_failure_is_not_fake_success() -> None:
    snapshot = PageSnapshot(
        url="https://blocked.invalid/",
        real=False,
        error="web.page_read DNS resolution failed",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=snapshot):
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
        text_preview="Acme HVAC serves Dallas. Contact Acme HVAC at service@acmehvac.example",
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
        "backend.services.tools.web_action_contacts.fetch_public_page",
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
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", side_effect=[directory, official]):
        result = research_observe_contacts(invocation, _context())

    promoted = result.output["verified_prospect_candidates"]
    assert len(promoted) == 1
    assert promoted[0]["company"] == "Acme HVAC"
    assert promoted[0]["prospect_id"] == "web:resolved:acmehvac.example"
    assert promoted[0]["identity_status"] == "verified"
    assert promoted[0]["identity_evidence_urls"] == [directory.url, official.url]
    assert result.output["observed_contacts"][0]["website"] == official.url


def test_observe_contacts_uses_linked_title_when_directory_label_is_generic() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    directory = PageSnapshot(
        url="https://directory.example/hvac",
        real=True,
        status_code=200,
        title="Dallas HVAC directory",
        text_preview="Browse local HVAC companies in Dallas.",
        body_preview="",
        extraction={"links": [{"url": "https://cool.example/", "text": "Visit website"}]},
        access_mode=InternetAccessMode.PAGE_READ,
    )
    official = PageSnapshot(
        url="https://cool.example/",
        real=True,
        status_code=200,
        title="Cool Air Heating",
        text_preview="Cool Air Heating provides HVAC and air conditioning services in Dallas, Texas.",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [{"company": "Dallas HVAC directory", "domain": "directory.example", "url": directory.url}],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", side_effect=[directory, official]):
        result = research_observe_contacts(invocation, _context())

    assert result.output["verified_prospect_candidates"][0]["company"] == "Cool Air Heating"


def test_observe_contacts_keeps_verified_company_without_contact_details() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    official = PageSnapshot(
        url="https://quiet-hvac.example/",
        real=True,
        status_code=200,
        title="Quiet HVAC",
        text_preview="Quiet HVAC provides heating and cooling services in Dallas.",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "Quiet HVAC",
                    "domain": "quiet-hvac.example",
                    "url": official.url,
                    "website": official.url,
                    "research_summary": "Heating and cooling services in Dallas.",
                }
            ],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=official):
        result = research_observe_contacts(invocation, _context())

    assert len(result.output["verified_prospect_candidates"]) == 1
    assert result.output["verified_prospect_candidates"][0]["identity_status"] == "verified"
    assert result.output["observed_contacts"] == [
        {
            "kind": None,
            "value": None,
            "source_url": official.url,
            "real": True,
            "company": "Quiet HVAC",
            "domain": "quiet-hvac.example",
            "website": official.url,
            "product_description": "",
            "research_summary": "Heating and cooling services in Dallas.",
            "sources": [official.url],
            "prospect_id": None,
            "identity_status": "verified",
            "identity_evidence_urls": [official.url],
        }
    ]


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
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=listing):
        result = research_observe_contacts(invocation, _context())

    assert result.output["prospect_candidates"][0]["identity_status"] == "unverified"
    assert result.output["observed_contacts"] == []


def test_observe_contacts_rejects_marketplace_page_even_when_host_matches() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    marketplace = PageSnapshot(
        url="https://downtobid.com/contractors/hvac/dallas",
        real=True,
        status_code=200,
        title="15 Best Commercial HVAC Contractors Dallas, TX",
        text_preview="Find and invite the best commercial HVAC contractors in Dallas. Access our contractor database.",
        body_preview="Browse contractors and submit bid requests.",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "15 Best Commercial HVAC Contractors Dallas, TX",
                    "domain": "downtobid.com",
                    "url": marketplace.url,
                }
            ],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=marketplace):
        result = research_observe_contacts(invocation, _context())

    page = result.output["pages"][0]
    assert page["identity_status"] == "unverified"
    assert page["source_reliability"] == "directory_or_third_party"
    assert result.output["verified_prospect_candidates"] == []
    assert result.output["research_gap"] == (
        "no verified candidates produced; public identity observation rejected all candidate sources"
    )


def test_observe_contacts_normalizes_company_name_when_domain_proves_identity() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    official = PageSnapshot(
        url="https://tomscommercial.com/areas-we-serve/dallas",
        real=True,
        status_code=200,
        title="Commercial HVAC Services in Dallas, TX",
        text_preview="Tom's Commercial, Inc. provides commercial heating and air conditioning services in Dallas, Texas.",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "Commercial HVAC Services in Dallas, TX",
                    "domain": "tomscommercial.com",
                    "url": official.url,
                }
            ],
            "requested_quantity": 1,
            "binding_required": True,
        },
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=official):
        result = research_observe_contacts(invocation, _context())

    assert result.output["pages"][0]["identity_status"] == "verified"
    assert result.output["verified_prospect_candidates"][0]["identity_status"] == "verified"


def test_observe_contacts_uses_declared_industry_for_non_hvac_research() -> None:
    from backend.services.tools.web_actions import research_observe_contacts

    page = PageSnapshot(
        url="https://roof.example/",
        real=True,
        status_code=200,
        title="Dallas Commercial Roofing",
        text_preview="Roof Example provides commercial roofing services in Dallas, Texas.",
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": "Roof Example",
                    "industry": "commercial roofing",
                    "domain": "roof.example",
                    "url": page.url,
                }
            ],
            "requested_quantity": 1,
            "context": {"industry": "commercial roofing", "location": "Dallas"},
        },
    )
    with patch("backend.services.tools.web_action_contacts.fetch_public_page", return_value=page):
        result = research_observe_contacts(invocation, _context())

    assert result.output["verified_prospect_candidates"][0]["identity_status"] == "verified"
