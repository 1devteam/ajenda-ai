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
    assert set(result.output["source_partitions"]) == {"tenant_internal", "public_search"}
    assert result.output["source_partitions"]["public_search"]["candidate_count"] == 0


def test_public_search_directory_hits_are_forwarded_only_to_observation(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    monkeypatch.setattr(
        standalone_actions,
        "_fetch_governed_public_search",
        lambda **_kwargs: {
            "provider": "duckduckgo_html",
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
            "attempts": [{"provider": "duckduckgo_html", "outcome": "results", "result_count": 1}],
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
    assert (
        result.output["research_gap"]
        == "public search returned candidates but no verified individual company identities"
    )
    assert result.output["source"] == "duckduckgo_html"
    assert result.output["public_prospect_candidates"][0]["source_scope"] == "public_search"
    assert result.output["public_prospect_candidates"][0]["evidence_class"] == "public_candidate_unverified"


def test_relation_research_resolves_reference_page_before_peer_search(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    queries: list[str] = []

    def search(**kwargs):  # type: ignore[no-untyped-def]
        query = str(kwargs["query"])
        queries.append(query)
        if query == "1DevTeam official website":
            return {
                "provider": "duckduckgo_html",
                "results": [
                    {
                        "title": "1DevTeam · Software development and applied R&D",
                        "url": "https://www.1devteam.com/",
                        "snippet": "Software development and applied research.",
                        "real": True,
                    }
                ],
                "real": True,
                "error": None,
                "attempts": [{"provider": "duckduckgo_html", "outcome": "results", "result_count": 1}],
            }
        assert query.startswith("software development and applied R&D companies")
        return {
            "provider": "duckduckgo_html",
            "results": [
                {
                    "title": "1DevTeam",
                    "url": "https://www.1devteam.com/about",
                    "snippet": "Reference company",
                    "real": True,
                },
                {
                    "title": "Peer One",
                    "url": "https://peer-one.example/",
                    "snippet": "Software development and applied R&D services.",
                    "real": True,
                },
                {
                    "title": "Peer Two",
                    "url": "https://peer-two.example/",
                    "snippet": "Applied software research company.",
                    "real": True,
                },
                {
                    "title": "Peer Three",
                    "url": "https://peer-three.example/",
                    "snippet": "Software systems and R&D services.",
                    "real": True,
                },
            ],
            "real": True,
            "error": None,
            "attempts": [{"provider": "duckduckgo_html", "outcome": "results", "result_count": 4}],
        }

    monkeypatch.setattr(standalone_actions, "_fetch_governed_public_search", search)
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_public_page_snippet",
        lambda **_kwargs: {
            "url": "https://www.1devteam.com/",
            "status_code": 200,
            "title": "1DevTeam · Software development and applied R&D",
            "text_preview": "1DevTeam is a software development and applied R&D company building dependable systems.",
            "body_preview": "",
            "body_truncated": False,
            "real": True,
            "error": None,
            "access_mode": "page_read",
            "extraction": {"meta_description": "Software development and applied R&D company."},
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "1DevTeam",
                "company": "1DevTeam",
                "fetch_public_page": True,
                "include_public_search": True,
                "exclude_internal_records": True,
                "limit": 3,
                "context": {
                    "relation_requirements": [
                        {
                            "relation": "reference_company_business_type",
                            "reference_company": "1DevTeam",
                            "reference_domain": None,
                            "required_for": "prospect_search",
                        }
                    ]
                },
            },
        ),
        _context(),
    )

    relation = result.output["business_type_relation"]
    assert relation["reference_company"] == "1DevTeam"
    assert relation["business_type"] == "software development and applied R&D"
    assert relation["source_url"] == "https://www.1devteam.com/"
    assert queries[0] == "1DevTeam official website"
    assert queries[1].startswith("software development and applied R&D companies")
    assert len(result.output["prospect_candidates"]) == 3
    assert all(item["domain"] != "1devteam.com" for item in result.output["prospect_candidates"])
    assert {item["company"] for item in result.output["prospect_candidates"]} == {
        "Peer One",
        "Peer Two",
        "Peer Three",
    }
    assert {item["phase"] for item in result.output["provider_attempts"]} == {
        "reference_lookup",
        "peer_discovery",
    }


def test_relation_research_does_not_promote_lookup_hits_without_category_evidence(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    monkeypatch.setattr(
        standalone_actions,
        "_fetch_governed_public_search",
        lambda **_kwargs: {
            "provider": "duckduckgo_html",
            "results": [
                {
                    "title": "People named 1DevTeam",
                    "url": "https://linkedin.com/search/results/companies/?keywords=1devteam",
                    "snippet": "Directory results",
                    "real": True,
                }
            ],
            "real": True,
            "error": None,
            "attempts": [{"provider": "duckduckgo_html", "outcome": "results", "result_count": 1}],
        },
    )
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_public_page_snippet",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("directory hit must not be fetched as official")),
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "1DevTeam",
                "company": "1DevTeam",
                "fetch_public_page": True,
                "include_public_search": True,
                "exclude_internal_records": True,
                "context": {
                    "relation_requirements": [
                        {
                            "relation": "reference_company_business_type",
                            "reference_company": "1DevTeam",
                            "reference_domain": None,
                            "required_for": "prospect_search",
                        }
                    ]
                },
            },
        ),
        _context(),
    )

    assert result.output["business_type_relation"] is None
    assert result.output["prospect_candidates"] == []
    assert result.output["research_gap"] == "reference company official page could not be resolved"
    assert result.output["relation_resolution"] == {
        "status": "reference_page_unresolved",
        "reason": "reference company official page could not be resolved",
        "reference_company": "1DevTeam",
        "reference_url": None,
        "reference_lookup_real": True,
    }


def test_relation_research_valid_empty_requires_resolved_category_and_real_peer_search(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    def search(**kwargs):  # type: ignore[no-untyped-def]
        query = str(kwargs["query"])
        if query == "1DevTeam official website":
            results = [{"title": "1DevTeam", "url": "https://1devteam.com/", "real": True}]
        else:
            results = []
        return {
            "provider": "duckduckgo_html",
            "results": results,
            "real": True,
            "error": None,
            "attempts": [{"provider": "duckduckgo_html", "outcome": "results", "result_count": len(results)}],
        }

    monkeypatch.setattr(standalone_actions, "_fetch_governed_public_search", search)
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_public_page_snippet",
        lambda **_kwargs: {
            "url": "https://1devteam.com/",
            "status_code": 200,
            "title": "1DevTeam",
            "text_preview": "1DevTeam is a software development and applied R&D company.",
            "body_preview": "",
            "body_truncated": False,
            "real": True,
            "error": None,
            "access_mode": "page_read",
            "extraction": {},
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "1DevTeam",
                "company": "1DevTeam",
                "include_public_search": True,
                "relation_requirements": [
                    {
                        "relation": "reference_company_business_type",
                        "reference_company": "1DevTeam",
                    }
                ],
                "limit": 3,
            },
        ),
        _context(),
    )

    assert result.output["business_type_relation"]["business_type"] == "software development and applied R&D"
    assert result.output["peer_search_real"] is True
    assert result.output["prospect_candidates"] == []
    assert result.output["research_gap"] == "peer search returned no result URLs"
    assert result.output["valid_empty_result"] == {
        "classification": "valid_empty",
        "reason": "peer search completed with no result URLs",
    }


def test_relation_research_reports_failed_explicit_reference_page_without_peer_search(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    monkeypatch.setattr(
        standalone_actions,
        "_fetch_governed_public_search",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("peer search must wait for category evidence")),
    )
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_public_page_snippet",
        lambda **_kwargs: {
            "url": "https://1devteam.com/",
            "status_code": None,
            "title": "",
            "text_preview": "",
            "body_preview": "",
            "body_truncated": False,
            "real": False,
            "error": "timeout",
            "access_mode": "page_read",
            "extraction": {},
        },
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "1DevTeam",
                "company": "1DevTeam",
                "domain": "1devteam.com",
                "include_public_search": True,
                "relation_requirements": [
                    {
                        "relation": "reference_company_business_type",
                        "reference_company": "1DevTeam",
                        "reference_domain": "1devteam.com",
                    }
                ],
            },
        ),
        _context(),
    )

    assert result.output["reference_lookup_real"] is False
    assert result.output["search_queries"] == []
    assert result.output["relation_resolution"]["status"] == "reference_page_read_failed"
    assert result.output["research_gap"] == "reference company official page could not be read"
    assert result.output["prospect_candidates"] == []


def test_relation_category_uses_page_identity_alias_for_domain_anchor() -> None:
    from backend.services.tools.standalone_actions import _derive_business_type_relation

    relation = _derive_business_type_relation(
        reference_company="1devteam.com",
        page={
            "url": "https://1devteam.com/",
            "status_code": 200,
            "real": True,
            "title": "1DevTeam · Software development and applied R&D",
            "text_preview": (
                "1DevTeam is a software development and applied R&D company that works alongside AI "
                "to solve difficult software and systems problems."
            ),
            "extraction": {"meta_description": "1DevTeam is a software development and applied R&D company."},
        },
    )

    assert relation is not None
    assert relation["reference_company"] == "1devteam.com"
    assert relation["business_type"] == "software development and applied R&D"


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
        "_fetch_governed_public_search",
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
    assert result.output["source"] == "ajenda_brain"
    assert result.output["source_partitions"]["tenant_internal"]["candidate_count"] == 1
    assert result.output["source_partitions"]["public_search"]["result_count"] == 0


def test_public_only_web_research_never_queries_tenant_or_crm_sources(monkeypatch) -> None:
    from backend.services.tools import standalone_actions

    def forbidden(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("public-only research attempted an internal source read")

    monkeypatch.setattr(standalone_actions, "resolve_record_store", forbidden)
    monkeypatch.setattr(standalone_actions, "default_crm_client", forbidden)
    monkeypatch.setattr(
        standalone_actions,
        "_fetch_governed_public_search",
        lambda **_kwargs: {"provider": "duckduckgo_html", "results": [], "real": True, "error": None},
    )

    result = get_default_action_registry(rebuild=True).invoke(
        ToolInvocation(
            action="web.research",
            input={
                "query": "early stage SaaS companies in Austin",
                "include_public_search": True,
                "exclude_internal_records": True,
            },
        ),
        _context(),
    )

    assert result.output["exclude_internal_records"] is True
    assert result.output["internal_count"] == 0
    assert result.output["crm_brain_matches"] == []
    assert result.output["source_partitions"]["tenant_internal"]["candidate_count"] == 0


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
    assert all(candidate["source_scope"] == "local_fixture" for candidate in result.output["prospect_candidates"])
    assert result.output["source_partitions"]["tenant_internal"]["evidence_class"] == "fixture"
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
    from backend.services.business_profile.context_resolver import BusinessContext
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
        "_fetch_governed_public_search",
        lambda **_kwargs: {"provider": "duckduckgo_html", "results": [], "real": True, "error": None},
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
    assert result.output["source"] == "duckduckgo_html"
    assert result.output["candidates_real"] is False
    assert "Ajenda AI" not in str(result.output.get("query"))


def test_web_research_does_not_mix_explicit_company_with_profile_domain(monkeypatch) -> None:
    """Codex P2: explicit prospect target must not inherit tenant profile domain."""
    from backend.services.business_profile.context_resolver import BusinessContext
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
        "_fetch_governed_public_search",
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
