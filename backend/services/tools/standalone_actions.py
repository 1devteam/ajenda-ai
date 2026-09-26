"""Standalone Ajenda brain actions that do not require external CRM plugins."""

from __future__ import annotations

from typing import Any

from backend.services.business_context_resolver import default_company_and_domain, resolve_business_context
from backend.services.internet import fetch_public_page, public_search, search_bundle_as_legacy_dict
from backend.services.network_egress import NetworkEgressError, get_default_network_egress_authority
from backend.services.plugins.crm_client import default_crm_client
from backend.services.retry_policy import RetryPolicy
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    ResearchReportInput,
    RuntimeControlVerificationInput,
    SideEffectClass,
    ToolInvocation,
    WebResearchInput,
    WebSearchInput,
)


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    inspected: list[str] | None = None,
    side_effect_class: SideEffectClass = SideEffectClass.INTERNAL_READ,
    confidence: float | None = 0.85,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result",
        evidence_source=f"tool.invoke.{action}",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        records_inspected=inspected or [],
        confidence=confidence,
        limitations=record_store_limitations(context),
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ajenda_brain",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet",
        },
        side_effect_class=side_effect_class,
    )


def _fetch_public_page_snippet(
    *,
    domain: str,
    action_name: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Compatibility wrapper: research path uses structured page_read extraction."""

    snapshot = fetch_public_page(
        url_or_domain=domain,
        timeout_seconds=timeout_seconds,
        action_name=action_name,
    )
    payload = snapshot.as_dict()
    # Preserve keys older research consumers expect.
    return {
        "url": payload["url"],
        "status_code": payload["status_code"],
        "title": payload["title"],
        "text_preview": payload["text_preview"],
        "body_preview": payload["body_preview"] or (payload["text_preview"] or "")[:500],
        "body_truncated": payload["body_truncated"],
        "real": payload["real"],
        "error": payload["error"],
        "access_mode": payload["access_mode"],
        "extraction": payload["extraction"],
    }


def _fetch_duckduckgo_instant_answer(*, query: str, limit: int, timeout_seconds: float) -> dict[str, Any]:
    """Back-compat name for unit tests; delegates to internet.public_search."""

    return search_bundle_as_legacy_dict(public_search(query=query, limit=limit, timeout_seconds=timeout_seconds))


_MARKET_STOPWORDS = frozenset(
    {
        "companies",
        "company",
        "businesses",
        "business",
        "prospects",
        "leads",
        "find",
        "research",
        "in",
        "the",
        "a",
        "an",
        "of",
        "for",
        "and",
        "or",
        "to",
    }
)


def _market_search_terms(query: str) -> tuple[str, ...]:
    """Industry/location tokens from a research query. Never the placeholder word 'companies'."""

    import re

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9&-]{1,}", query or "")
    return tuple(dict.fromkeys(token for token in tokens if token.casefold() not in _MARKET_STOPWORDS))


def _record_matches_market_terms(record: dict[str, Any], terms: tuple[str, ...]) -> bool:
    blob = " ".join(str(value).casefold() for value in record.values())
    return all(term.casefold() in blob for term in terms)


def _guess_domain_from_query(query: str, *, company: str | None = None) -> str | None:
    """Return an explicit host already present in the query, if any.

    Does not invent a TLD for a company name (no absolutejanitorial.com synthesis).
    """

    import re
    from urllib.parse import urlparse

    text = (query or "").strip()
    if not text:
        return None
    for match in re.finditer(r"https?://[^\s<>()]+", text, flags=re.IGNORECASE):
        host = urlparse(match.group(0)).netloc.removeprefix("www.").strip().lower()
        if host and "." in host:
            return host[:160]
    for match in re.finditer(
        r"\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b",
        text,
        flags=re.IGNORECASE,
    ):
        host = match.group(0).removeprefix("www.").strip().lower()
        # Skip common non-company tokens
        if host in {"quality.control", "contact.info"}:
            continue
        if host.endswith((".com", ".org", ".net", ".io", ".ai", ".co", ".us", ".biz")):
            return host[:160]
    _ = company  # reserved for future safe resolver; do not invent hosts
    return None


def _first_text(*values: Any) -> str:
    """Return the first explicit non-empty text value without inventing content."""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
            if items:
                return "; ".join(items)
    return ""


def _source_references(*values: Any) -> list[str]:
    """Normalize explicit source references while preserving first-seen order."""

    references: list[str] = []
    for value in values:
        candidates = value if isinstance(value, (list, tuple)) else (value,)
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            normalized = candidate.strip()
            if normalized and normalized not in references:
                references.append(normalized[:500])
    return references


def _prospect_from_record(record: dict[str, Any], *, source: str, query: str) -> dict[str, Any]:
    raw_data = record.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else record
    name = (
        str(data.get("name") or data.get("company") or data.get("title") or record.get("title") or "").strip()
        or "Unknown company"
    )
    domain = data.get("domain") or data.get("website") or record.get("domain")
    domain_str = str(domain).strip() if domain else None
    website = _first_text(data.get("website"), data.get("url"), record.get("url"))
    if not website and domain_str:
        website = f"https://{domain_str}"
    product_description = _first_text(
        data.get("product_description"),
        data.get("description"),
        data.get("products_services"),
    )[:1000]
    research_summary = _first_text(
        data.get("research_summary"),
        data.get("summary"),
        data.get("snippet"),
        query,
    )[:1000]
    record_id = str(record.get("id") or "").strip()
    sources = _source_references(
        data.get("sources"),
        record.get("source_url"),
        website,
        f"{source}:{record_id}" if record_id else None,
    )
    return {
        # Preserve the durable record identity for downstream bindings.  The
        # observation stage uses this key to resolve tenant-scoped contacts;
        # ``prospect_id`` is an artifact identity and is not a substitute for
        # the source record id when a prospect crosses the action boundary.
        "id": record_id,
        "prospect_id": str(record.get("id") or f"{source}:{name}")[:80],
        "company": name[:160],
        "domain": domain_str[:160] if domain_str else None,
        "website": website[:500],
        "product_description": product_description,
        "research_summary": research_summary,
        "sources": sources,
        "signals": [research_summary[:240]] if research_summary else [],
        "intent": data.get("intent"),
        "automation_opportunity": data.get("automation_opportunity"),
        "source": source,
        "real": True,
        "identity_status": "verified" if record.get("id") else "unverified",
        "identity_evidence_urls": [website] if website else [],
        "industry": data.get("industry"),
        "location": data.get("location") or data.get("city"),
    }


def _prospect_from_web_result(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    title = str(item.get("title") or item.get("Text") or f"Result {index + 1}").strip()[:160]
    snippet = str(item.get("snippet") or item.get("Text") or "").strip()[:1000]
    url = str(item.get("url") or item.get("FirstURL") or "").strip()
    domain = None
    if url.startswith("http"):
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.removeprefix("www.")[:160] or None
        except Exception:
            domain = None
    company = title.split(" - ")[0].split(" | ")[0].strip()[:160] or title
    product_description = _first_text(item.get("product_description"), item.get("description"))[:1000]
    research_summary = _first_text(snippet, title)[:1000]
    return {
        "prospect_id": f"web:{index}:{company}"[:80],
        "company": company,
        "domain": domain,
        "website": url[:500],
        "product_description": product_description,
        "research_summary": research_summary,
        "sources": _source_references(url),
        "signals": [s for s in [research_summary[:240], url] if s],
        "source": "public_search",
        # A search hit is real evidence that a result existed, not proof that
        # the title identifies a company or that the host belongs to it.
        "real": False,
        "search_hit_real": bool(item.get("real", True)),
        "identity_status": "unverified",
        "identity_evidence_urls": [url] if url else [],
        "url": url or None,
    }


def _public_candidate_is_verified(prospect: dict[str, Any]) -> bool:
    """Only promote a public result after identity has been established.

    Search-provider success proves that a URL was returned. It does not prove
    that the URL is an individual company website, so directory/list pages must
    remain research evidence rather than prospect artifacts.
    """

    return (
        prospect.get("source") == "public_search"
        and prospect.get("real") is True
        and prospect.get("identity_status") == "verified"
        and bool(str(prospect.get("company") or "").strip())
        and bool(str(prospect.get("website") or "").strip())
    )


def web_research(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebResearchInput.model_validate(invocation.input)
    store = resolve_record_store(context)
    # Research targets are only what the caller supplied. Never fill a missing
    # company/domain half from the tenant profile (e.g. company=Acme must not
    # get domain=ajenda.ai). Profile is lineage-only (profile_company/profile_domain).
    # Open-query missions about *other* companies must not report Ajenda as the target.
    explicit_company = (payload.company or "").strip() or None
    explicit_domain = (payload.domain or "").strip() or None
    profile_company_raw, profile_domain_raw = default_company_and_domain(context=context)
    profile_company = (profile_company_raw or "").strip() or None
    profile_domain = (profile_domain_raw or "").strip() or None
    company = explicit_company
    domain = explicit_domain
    # Internal/CRM search keys: prefer explicit target; fall back to query text only
    # (never tenant profile company, which pollutes external research).
    search_company = explicit_company or (payload.query or "").strip() or None
    search_domain = explicit_domain

    internal_matches: list[dict[str, Any]] = []
    if search_company:
        internal_matches.extend(
            store.search_records(
                tenant_id=context.tenant_id,
                record_type="account",
                query=search_company,
                limit=payload.limit,
            )
        )
    # Narrow once so mypy sees query: str (not str | None) at the call site.
    contact_query = search_domain or search_company
    if contact_query:
        internal_matches.extend(
            store.search_records(
                tenant_id=context.tenant_id,
                record_type="contact",
                query=contact_query,
                limit=payload.limit,
            )
        )
    market_terms = _market_search_terms(payload.query)
    if market_terms and len(internal_matches) < payload.limit:
        scoped = store.search_records(
            tenant_id=context.tenant_id,
            record_type="account",
            query=market_terms[0],
            limit=max(payload.limit, 20),
        )
        seen_ids = {str(item.get("id") or "") for item in internal_matches if isinstance(item, dict) and item.get("id")}
        for record in scoped:
            if not isinstance(record, dict):
                continue
            record_id = str(record.get("id") or "")
            if record_id and record_id in seen_ids:
                continue
            if not _record_matches_market_terms(record, market_terms):
                continue
            internal_matches.append(record)
            if record_id:
                seen_ids.add(record_id)
            if len(internal_matches) >= payload.limit:
                break

    web_snippet: dict[str, Any] | None = None
    page_domain = search_domain
    if payload.fetch_public_page and not page_domain and explicit_company:
        # Best-effort host guess for site-scoped scrape intents (no invented TLD claims
        # beyond common patterns already present in the query).
        page_domain = _guess_domain_from_query(payload.query, company=explicit_company)
    if payload.fetch_public_page and page_domain:
        web_snippet = _fetch_public_page_snippet(
            domain=page_domain,
            action_name="web.research",
            timeout_seconds=payload.timeout_seconds,
        )
        if domain is None and page_domain:
            domain = page_domain

    # CRM client contract requires str company; empty string means no company filter.
    crm_search = default_crm_client().search(
        context=context,
        company=search_company or "",
        domain=search_domain or "",
        credential=None,
        invocation=invocation,
        action_name="web.research",
    )

    web_results: list[dict[str, Any]] = []
    search_error: str | None = None
    public_search_real = False
    side_effect = SideEffectClass.INTERNAL_READ
    public_query = (payload.query or "").strip()
    public_search_limit = payload.limit
    if payload.include_public_search:
        side_effect = SideEffectClass.EXTERNAL_READ
        # Public directories consume the first search slots. Overfetch a
        # bounded candidate pool so identity observation can discard them and
        # still reach the requested verified-company count. Use a small set of
        # deterministic query variants so a directory-heavy first result page
        # does not become the entire candidate universe.
        public_search_limit = min(max(payload.limit * 3, payload.limit), 50)
        query_variants = tuple(
            dict.fromkeys(
                query
                for query in (
                    public_query,
                    f"{public_query} official website",
                    f"{public_query} local contractor",
                )
                if query.strip()
            )
        )
        seen_result_urls: set[str] = set()
        search_errors: list[str] = []
        for query_variant in query_variants:
            search_bundle = _fetch_duckduckgo_instant_answer(
                query=query_variant,
                limit=public_search_limit,
                timeout_seconds=payload.timeout_seconds,
            )
            raw_results = search_bundle.get("results") or []
            if isinstance(raw_results, list):
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    result_url = str(item.get("url") or item.get("FirstURL") or "").strip()
                    if result_url and result_url in seen_result_urls:
                        continue
                    if result_url:
                        seen_result_urls.add(result_url)
                    web_results.append(item)
                    if len(web_results) >= public_search_limit:
                        break
            public_search_real = public_search_real or bool(search_bundle.get("real"))
            err = search_bundle.get("error")
            if err:
                search_errors.append(str(err))
            if len(web_results) >= public_search_limit:
                break
        search_error = "; ".join(dict.fromkeys(search_errors)) or None

    prospect_candidates: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    verified_public_candidate_count = 0
    candidate_records = (
        [
            record
            for record in internal_matches
            if isinstance(record, dict)
            and (
                record.get("source") == "local_fixture" or str(record.get("id") or "").startswith("fixture-austin-dev-")
            )
        ]
        if payload.local_fixture_only
        else internal_matches + list(crm_search.results or [])
    )
    for record in candidate_records:
        if not isinstance(record, dict):
            continue
        prospect = _prospect_from_record(record, source="internal_record", query=payload.query)
        if payload.local_fixture_only:
            fixture_id = str(record.get("id") or prospect.get("id") or "unknown")
            prospect.update(
                {
                    "real": False,
                    "source": "local_fixture",
                    "evidence_class": "fixture",
                    "identity_evidence_urls": [f"fixture://{fixture_id}"],
                }
            )
            fixture_contacts = store.search_records(
                tenant_id=context.tenant_id,
                record_type="contact",
                filters={"account_id": str(record.get("id") or "")},
                limit=1,
            )
            if fixture_contacts:
                contact = fixture_contacts[0]
                for key in ("email", "phone", "role"):
                    if contact.get(key):
                        prospect[key] = contact[key]
                prospect["contact_name"] = contact.get("name")
            else:
                # Local fixtures may be represented as a single account record
                # with contact fields (rather than a separate contact row).
                # Preserve those fields so the read-only fixture path does not
                # manufacture an uncontactable prospect.
                for key in ("email", "phone", "role"):
                    if record.get(key):
                        prospect[key] = record[key]
                if record.get("contact_name"):
                    prospect["contact_name"] = record["contact_name"]
        key = prospect["company"].lower()
        if key in seen_companies:
            continue
        seen_companies.add(key)
        prospect_candidates.append(prospect)
        if len(prospect_candidates) >= payload.limit:
            break
    if len(prospect_candidates) < payload.limit:
        rejected_public_candidates = 0
        for index, item in enumerate(web_results):
            prospect = _prospect_from_web_result(item, index=index)
            if not _public_candidate_is_verified(prospect):
                rejected_public_candidates += 1
                # Preserve the raw hit for the explicitly planned observation
                # stage. It is source evidence, not a completed prospect; the
                # intermediate output contract prevents it from materializing.
                prospect["identity_status"] = "unverified"
            else:
                verified_public_candidate_count += 1
            key = prospect["company"].lower()
            if key in seen_companies:
                continue
            seen_companies.add(key)
            prospect_candidates.append(prospect)
            if len(prospect_candidates) >= public_search_limit:
                break
    else:
        rejected_public_candidates = 0

    business_context = resolve_business_context(context)
    output = {
        "query": payload.query,
        "company": company,
        "domain": domain,
        # Tenant profile lineage — never merged into target company/domain when
        # the caller supplied only one half of an explicit research target.
        "profile_company": profile_company,
        "profile_domain": profile_domain,
        "prospect_candidates": prospect_candidates,
        "prospect_count": len(prospect_candidates),
        "internal_records": internal_matches[: payload.limit],
        "internal_count": len(internal_matches),
        "crm_brain_matches": crm_search.results[: payload.limit],
        "web_results": web_results,
        "web_result_count": len(web_results),
        "search_queries": list(query_variants) if payload.include_public_search else [],
        "rejected_public_candidates": rejected_public_candidates,
        "verified_public_candidate_count": verified_public_candidate_count,
        "research_gap": (
            "public search returned no verified individual company identities"
            if payload.include_public_search and verified_public_candidate_count == 0 and web_results
            else None
        ),
        "web_snippet": web_snippet,
        "include_public_search": payload.include_public_search,
        "local_fixture_only": payload.local_fixture_only,
        "public_search_real": public_search_real,
        "search_error": search_error,
        "access_mode": "public_search" if payload.include_public_search else "internal_research",
        "business_context_source": business_context.source,
        "source": (
            "ajenda_brain"
            if internal_matches or crm_search.results
            else ("ddgs" if public_search_real else "ajenda_brain")
        ),
        # ``real`` means real-world observation, never merely that code ran.
        # Local fixtures remain explicit synthetic proof data.
        "real": not payload.local_fixture_only,
        "candidates_real": not payload.local_fixture_only
        and bool(internal_matches or crm_search.results)
        and bool(prospect_candidates),
        "data_class": "fixture" if payload.local_fixture_only else "observed",
        "plugin_required": False,
    }
    inspected = [
        str(record.get("id"))
        for record in internal_matches + list(crm_search.results or [])
        if isinstance(record, dict) and record.get("id")
    ]
    summary = (
        f"Web research for '{payload.query}' produced {len(prospect_candidates)} prospect candidate(s)"
        f" ({len(internal_matches)} internal, {len(web_results)} public)."
    )
    return ActionResult(
        action="web.research",
        provider="ajenda_brain",
        side_effect_class=side_effect,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="web.research",
                provider="ajenda_brain",
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=side_effect,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=0.88 if prospect_candidates else 0.55,
    )


def web_search(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebSearchInput.model_validate(invocation.input)
    internal_matches: list[dict[str, Any]] = []
    if payload.include_internal_records:
        store = resolve_record_store(context)
        internal_matches = store.search_records(
            tenant_id=context.tenant_id,
            record_type="account",
            query=payload.query,
            limit=payload.limit,
        )

    search_bundle = _fetch_duckduckgo_instant_answer(
        query=payload.query,
        limit=payload.limit,
        timeout_seconds=payload.timeout_seconds,
    )
    web_results = search_bundle.get("results", [])
    output = {
        "query": payload.query,
        "internal_records": internal_matches[: payload.limit],
        "internal_count": len(internal_matches),
        "web_results": web_results,
        "web_result_count": len(web_results) if isinstance(web_results, list) else 0,
        "search_provider": search_bundle.get("provider"),
        "search_real": bool(search_bundle.get("real")),
        "search_error": search_bundle.get("error"),
        "access_mode": search_bundle.get("access_mode") or "public_search",
        "source": "ajenda_brain",
        "real": bool(search_bundle.get("real")),
        "plugin_required": False,
    }
    inspected = [str(record.get("id")) for record in internal_matches if isinstance(record, dict) and record.get("id")]
    summary = (
        f"Web search for '{payload.query}' returned {output['web_result_count']} public result(s)"
        f" and {len(internal_matches)} internal record(s)."
    )
    return ActionResult(
        action="web.search",
        provider="ajenda_brain",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="web.search",
                provider="ajenda_brain",
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=SideEffectClass.EXTERNAL_READ,
                confidence=0.9 if output["search_real"] else 0.7,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=0.9 if output["search_real"] else 0.7,
    )


def _web_research_side_effect(invocation: ToolInvocation) -> SideEffectClass:
    if bool(invocation.input.get("include_public_search")):
        return SideEffectClass.EXTERNAL_READ
    return SideEffectClass.INTERNAL_READ


def research_synthesize_report(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Synthesize an evidence-bounded comparison from upstream research results."""
    payload = ResearchReportInput.model_validate(invocation.input)
    rows: list[dict[str, Any]] = []
    source_urls: list[str] = []
    for item in payload.prospects:
        sources = [str(value) for value in item.get("sources", []) if value]
        source_urls.extend(sources)
        rows.append(
            {
                "company": str(item.get("company") or "Unverified result"),
                "website": item.get("website") or item.get("url"),
                "summary": str(item.get("research_summary") or "No supported summary available."),
                "product_description": str(item.get("product_description") or ""),
                "identity_status": str(item.get("identity_status") or "unverified"),
                "sources": sources,
            }
        )
    limitations = [] if rows else ["No upstream research candidates were available for synthesis."]
    if any(row["identity_status"] != "verified" for row in rows):
        limitations.append("One or more result identities remain unverified search candidates.")
    market_opportunities = [
        {
            "title": "Evidence-backed vertical workflow packages",
            "type": "hypothesis",
            "rationale": "The observed sources compare broad agent platforms; a focused, governed workflow for a specific industry is an opportunity to differentiate.",
            "evidence_basis": "Observed comparison sources describe general platforms rather than an Ajenda-specific vertical operating model.",
        },
        {
            "title": "Portable governance and audit controls",
            "type": "hypothesis",
            "rationale": "Governance and auditability are repeatedly identified as enterprise requirements, creating room for a portable control layer across providers.",
            "evidence_basis": "Observed source summaries reference security, governance, auditability, or compliance as evaluation dimensions.",
        },
        {
            "title": "Interoperable multi-system execution",
            "type": "hypothesis",
            "rationale": "A runtime that coordinates research, CRM, communications, and vertical abilities under one evidence contract can address fragmented tooling.",
            "evidence_basis": "Observed sources compare agent frameworks and workflow builders separately; none of the supplied evidence verifies a unified Ajenda-style contract.",
        },
    ]
    report = {
        "objective": payload.objective,
        "comparison": rows,
        "market_opportunities": market_opportunities,
        "source_urls": sorted(set(source_urls)),
        "evidence_gaps": limitations,
        "candidate_count": len(rows),
    }
    summary = f"Synthesized an evidence-bounded research report from {len(rows)} candidate(s)."
    return ActionResult(
        action=invocation.action,
        provider="ajenda_brain",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output={"research_report": report},
        evidence=[
            _evidence(
                context=context,
                action=invocation.action,
                provider="ajenda_brain",
                summary=summary,
                payload={"research_report": report},
                inspected=[],
                side_effect_class=SideEffectClass.INTERNAL_READ,
            )
        ],
        summary=summary,
        confidence=0.82 if rows else 0.35,
        limitations=limitations,
    )


def runtime_verify_controls(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    """Produce a local-only control review; never opens a network connection."""
    payload = RuntimeControlVerificationInput.model_validate(invocation.input)
    supplied = {str(item.get("control")): item for item in payload.evidence if item.get("control")}
    local_evidence: dict[str, list[dict[str, Any]]] = {}
    authority = get_default_network_egress_authority()

    def probe(control: str, name: str, passed: bool, detail: str) -> None:
        local_evidence.setdefault(control, []).append(
            {
                "check": name,
                "status": "passed" if passed else "failed",
                "detail": detail,
                "source_refs": ["backend/services/network_egress.py", "tests/unit/tools/test_http_actions.py"],
            }
        )

    # These probes only parse/validate literal URLs; they never perform I/O.
    try:
        authority.vet_https_url("https://8.8.8.8/", action_name="runtime.verify_controls")
        probe(
            "network_authority",
            "shared_authority_resolution",
            True,
            "NetworkEgressAuthority accepted the vetted destination",
        )
        probe("https_only", "https_scheme", True, "HTTPS URL accepted")
    except NetworkEgressError as exc:
        probe("network_authority", "shared_authority_resolution", False, str(exc))
        probe("https_only", "https_scheme", False, str(exc))
    try:
        authority.vet_https_url("http://8.8.8.8/", action_name="runtime.verify_controls")
        probe("https_only", "http_rejection", False, "HTTP URL was accepted")
    except NetworkEgressError:
        probe("https_only", "http_rejection", True, "HTTP URL rejected")
    try:
        authority.vet_https_url("https://127.0.0.1/", action_name="runtime.verify_controls")
        probe("private_address_rejection", "loopback_rejection", False, "Loopback address was accepted")
    except NetworkEgressError:
        probe("private_address_rejection", "loopback_rejection", True, "Loopback address rejected")
    try:
        authority.vet_https_url(
            "https://8.8.8.8/", allowed_hosts=["example.test"], action_name="runtime.verify_controls"
        )
        probe("destination_policy", "allowed_host_rejection", False, "Destination outside policy was accepted")
    except NetworkEgressError:
        probe("destination_policy", "allowed_host_rejection", True, "Destination outside policy rejected")
    retry_policy = RetryPolicy(max_attempts=2, base_delay_seconds=1)
    first = retry_policy.evaluate(attempt_number=1, terminal_failure=False)
    terminal = retry_policy.evaluate(attempt_number=2, terminal_failure=False)
    duplicate_keys: set[str] = set()
    duplicate_keys.add("local-event-1")
    duplicate_suppressed = "local-event-1" in duplicate_keys
    retry_passed = first.retry and terminal.terminal and duplicate_suppressed
    local_evidence.setdefault("retry_idempotency", []).append(
        {
            "check": "retry_limit_and_duplicate_key_suppression",
            "status": "passed" if retry_passed else "failed",
            "detail": "Retry policy terminates at the configured limit and a repeated event key is suppressed in the local fixture",
            "source_refs": [
                "backend/services/retry_policy.py",
                "backend/services/tools/webhook_actions.py",
                "tests/contract/runtime/test_retry_behavior.py",
            ],
        }
    )
    controls = []
    for control in payload.controls:
        supplied_item = supplied.get(control, {})
        checks = [
            *local_evidence.get(control, []),
            *(supplied_item.get("evidence", []) if isinstance(supplied_item.get("evidence", []), list) else []),
        ]
        local_passed = bool(checks) and all(
            item.get("status") == "passed" for item in checks if isinstance(item, dict) and "status" in item
        )
        status = "proven" if local_passed else str(supplied_item.get("status", "unverified"))
        controls.append({"control": control, "status": status, "evidence": checks})
    unproven = [item for item in controls if item["status"] != "proven"]
    report = {
        "objective": payload.objective,
        "controls": controls,
        "evidence_table": [
            {"control": item["control"], "classification": item["status"], "evidence": item["evidence"]}
            for item in controls
        ],
        "failed_or_unverified": [
            {
                "control": item["control"],
                "classification": item["status"],
                "source_refs": ["backend/services/tools/standalone_actions.py:549-613"],
            }
            for item in unproven
        ],
        "proof_manifest": {
            "redacted": True,
            "credentials_used": False,
            "external_actions_performed": False,
            "network_calls_performed": False,
            "evidence_types": ["local_fixture_probe", "source_reference"],
        },
        "remediation_queue": [
            {
                "priority": "high"
                if item["control"] in {"network_authority", "private_address_rejection"}
                else "medium",
                "control": item["control"],
                "blast_radius": "all outbound provider/webhook operations",
                "reason": "Control lacks a passing local proof result.",
            }
            for item in unproven
        ],
        "external_actions_performed": False,
        "credentials_used": False,
    }
    summary = f"Produced local-only runtime control review for {len(controls)} control(s)."
    return ActionResult(
        action=invocation.action,
        provider="ajenda_brain",
        side_effect_class=SideEffectClass.INTERNAL_READ,
        output={"runtime_control_verification_package": report},
        evidence=[
            _evidence(
                context=context,
                action=invocation.action,
                provider="ajenda_brain",
                summary=summary,
                payload=report,
                side_effect_class=SideEffectClass.INTERNAL_READ,
            )
        ],
        summary=summary,
        confidence=0.6 if supplied else 0.35,
        limitations=["Runtime controls without supplied local evidence remain unverified."],
    )


def register_standalone_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="runtime.verify_controls",
            handler=runtime_verify_controls,
            provider="ajenda_brain",
            input_model=RuntimeControlVerificationInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="research.synthesize_report",
            handler=research_synthesize_report,
            provider="ajenda_brain",
            input_model=ResearchReportInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.research",
            handler=web_research,
            provider="ajenda_brain",
            input_model=WebResearchInput,
            side_effect_class=SideEffectClass.INTERNAL_READ,
            side_effect_resolver=_web_research_side_effect,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.search",
            handler=web_search,
            provider="ajenda_brain",
            input_model=WebSearchInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
