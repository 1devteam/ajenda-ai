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
    # Explicit company-only target must not invent a domain from tenant profile.
    assert result.output["company"] == "Acme Manufacturing"
    assert result.output["domain"] is None


def test_public_search_directory_hits_are_forwarded_only_to_observation(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    monkeypatch.setattr(
        standalone_actions,
        "_fetch_duckduckgo_instant_answer",
        lambda **_kwargs: {
            "results": [
                {
                    "title": "Top Arkansas HVAC Companies | Directory",
                    "url": "https://directory.example/hvac",
                    "snippet": "A directory result.",
                    "real": True,
                }
            ],
            "real": True,
            "error": None,
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "HVAC companies in Northwest Arkansas", "include_public_search": True},
        ),
        _context(),
    )

    assert len(result.output["prospect_candidates"]) == 1
    assert result.output["prospect_candidates"][0]["identity_status"] == "unverified"
    assert result.output["rejected_public_candidates"] == 1
    assert result.output["research_gap"] == "public search returned no verified individual company identities"


def test_web_research_matches_market_tokens_on_tenant_accounts(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    class _Store:
        def search_records(self, **kwargs):  # type: ignore[no-untyped-def]
            query = str(kwargs.get("query") or "")
            if kwargs.get("record_type") != "account":
                return []
            if query == "HVAC companies in Dallas":
                return []
            if query == "HVAC":
                return [
                    {
                        "id": "acct-dallas-hvac-1",
                        "name": "Dallas Comfort HVAC",
                        "industry": "HVAC",
                        "location": "Dallas",
                        "website": "https://dallascomfort.example",
                        "product_description": "Residential HVAC service in Dallas.",
                        "research_summary": "Dallas Comfort HVAC serves HVAC companies in Dallas.",
                        "sources": ["https://dallascomfort.example"],
                    }
                ]
            return []

    monkeypatch.setattr(standalone_actions, "resolve_record_store", lambda _ctx: _Store())
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_duckduckgo_instant_answer",
        lambda **_kwargs: {"results": [], "real": False, "error": None},
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "HVAC companies in Dallas", "include_public_search": True, "limit": 10},
        ),
        _context(),
    )
    assert result.output["prospect_count"] == 1
    assert result.output["prospect_candidates"][0]["company"] == "Dallas Comfort HVAC"


def test_local_fixture_research_preserves_source_ids_for_all_contacts(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    accounts = [
        {
            "id": f"fixture-{index}",
            "name": f"Austin Software {index}",
            "industry": "software development",
            "location": "Austin",
            "website": f"https://software-{index}.example",
            "source": "local_fixture",
        }
        for index in range(1, 6)
    ]
    contacts = {
        account["id"]: {
            "id": f"{account['id']}-contact",
            "account_id": account["id"],
            "name": f"{account['name']} Contact",
            "role": "Founder",
            "email": f"contact{account['id'].rsplit('-', 1)[-1]}@example.test",
        }
        for account in accounts
    }

    class _Store:
        def search_records(self, **kwargs):  # type: ignore[no-untyped-def]
            record_type = kwargs.get("record_type")
            if record_type == "account":
                return accounts
            if record_type == "contact":
                account_id = (kwargs.get("filters") or {}).get("account_id")
                contact = contacts.get(account_id)
                return [contact] if contact else []
            return []

    monkeypatch.setattr(standalone_actions, "resolve_record_store", lambda _ctx: _Store())
    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "software development companies in Austin",
                "include_public_search": False,
                "local_fixture_only": True,
                "limit": 5,
            },
        ),
        _context(),
    )

    candidates = result.output["prospect_candidates"]
    assert len(candidates) == 5
    assert all(candidate["id"] == candidate["prospect_id"] for candidate in candidates)
    assert all(candidate.get("email") for candidate in candidates)
    assert result.output["real"] is False
    assert result.output["candidates_real"] is False
    assert result.output["data_class"] == "fixture"
    assert all(candidate["real"] is False for candidate in result.output["prospect_candidates"])
    assert all(candidate["source"] == "local_fixture" for candidate in result.output["prospect_candidates"])
    assert all(candidate["evidence_class"] == "fixture" for candidate in result.output["prospect_candidates"])
    assert all(
        candidate["identity_evidence_urls"] == [f"fixture://{candidate['id']}"]
        for candidate in result.output["prospect_candidates"]
    )


def test_local_fixture_contact_match_is_not_promoted_to_prospect(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    account = {
        "id": "fixture-account-1",
        "name": "Austin Plumbing",
        "industry": "plumbing",
        "location": "Austin",
        "website": "https://austin-plumbing.example",
        "source": "local_fixture",
    }
    contact = {
        "id": "fixture-account-1-contact",
        "name": "Austin Plumbing Contact",
        "account_id": "fixture-account-1",
        "email": "owner@austin-plumbing.example",
        "source": "local_fixture",
    }

    class _Store:
        def search_records(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs.get("record_type") == "account":
                return [account]
            if kwargs.get("record_type") == "contact":
                return [contact]
            return []

    monkeypatch.setattr(standalone_actions, "resolve_record_store", lambda _ctx: _Store())
    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "plumbing companies in Austin", "local_fixture_only": True, "limit": 2},
        ),
        _context(),
    )

    assert [item["company"] for item in result.output["prospect_candidates"]] == ["Austin Plumbing"]
    assert all(item.get("website") for item in result.output["prospect_candidates"])


def test_web_research_open_query_does_not_use_profile_as_target(monkeypatch) -> None:
    """Open research about a third party must not report tenant profile as company/domain."""
    from backend.services.business_context_resolver import BusinessContext
    from backend.services.tools import standalone_actions

    profile = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain="ajenda.ai",
        website="https://ajenda.ai",
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=(),
        operator_notes=None,
        account_record_id=None,
        contact_record_id=None,
        source="business_profile",
    )
    monkeypatch.setattr(standalone_actions, "resolve_business_context", lambda _ctx: profile)
    monkeypatch.setattr(
        standalone_actions,
        "default_company_and_domain",
        lambda **_kwargs: ("Ajenda AI", "ajenda.ai"),
    )
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_duckduckgo_instant_answer",
        lambda **_kwargs: {"results": [], "real": True, "error": None},
    )

    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "Absolute Janitorial Sarah Bogert quality control contact",
                "include_public_search": True,
            },
        ),
        _context(),
    )
    assert result.output["company"] is None
    assert result.output["domain"] is None
    assert result.output["profile_company"] == "Ajenda AI"
    assert result.output["profile_domain"] == "ajenda.ai"
    assert result.output["source"] == "ddgs"
    assert result.output["candidates_real"] is False
    assert "Ajenda AI" not in str(result.output.get("query"))


def test_web_research_does_not_mix_explicit_company_with_profile_domain(monkeypatch) -> None:
    """Codex P2: explicit prospect target must not inherit tenant profile domain."""
    from backend.services.business_context_resolver import BusinessContext
    from backend.services.tools import standalone_actions

    profile = BusinessContext(
        business_name="Ajenda AI",
        company="Ajenda AI",
        domain="ajenda.ai",
        website="https://ajenda.ai",
        service_area=None,
        primary_contact_name=None,
        contact_email=None,
        contact_phone=None,
        target_customers=(),
        products_services=(),
        operator_notes=None,
        account_record_id=None,
        contact_record_id=None,
        source="business_profile",
    )
    monkeypatch.setattr(standalone_actions, "resolve_business_context", lambda _ctx: profile)
    monkeypatch.setattr(
        standalone_actions,
        "default_company_and_domain",
        lambda **_kwargs: ("Ajenda AI", "ajenda.ai"),
    )

    registry = get_default_action_registry(rebuild=True)
    result = registry.invoke(
        ToolInvocation(
            action="web.research",
            input={"query": "Acme Manufacturing roofing", "company": "Acme Manufacturing"},
        ),
        _context(),
    )
    assert result.output["company"] == "Acme Manufacturing"
    assert result.output["domain"] is None
    assert result.output["profile_company"] == "Ajenda AI"
    assert result.output["profile_domain"] == "ajenda.ai"
    # Evidence structured payload matches action output (no mixed target domain).
    evidence_payload = result.evidence[0].structured_payload or {}
    assert evidence_payload.get("domain") is None
    assert evidence_payload.get("profile_domain") == "ajenda.ai"


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
        "backend.services.internet.search.get_default_network_egress_authority",
        return_value=authority,
    ):
        bundle = _fetch_duckduckgo_instant_answer(query="HubSpot CRM", limit=5, timeout_seconds=10.0)

    assert bundle["real"] is True
    assert bundle["result_count"] >= 3
    assert bundle["access_mode"] == "public_search"


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
