"""Standalone Ajenda brain actions that do not require external CRM plugins."""

from __future__ import annotations

from typing import Any

from backend.services.business_context_resolver import default_company_and_domain, resolve_business_context
from backend.services.internet import fetch_public_page, public_search, search_bundle_as_legacy_dict
from backend.services.plugins.crm_client import default_crm_client
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.record_store import record_store_limitations, resolve_record_store
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
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


def _prospect_from_record(record: dict[str, Any], *, source: str, query: str) -> dict[str, Any]:
    raw_data = record.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else record
    name = (
        str(data.get("name") or data.get("company") or data.get("title") or record.get("title") or "").strip()
        or "Unknown company"
    )
    domain = data.get("domain") or data.get("website") or record.get("domain")
    domain_str = str(domain).strip() if domain else None
    return {
        "prospect_id": str(record.get("id") or f"{source}:{name}")[:80],
        "company": name[:160],
        "domain": domain_str[:160] if domain_str else None,
        "signals": [str(data.get("summary") or data.get("snippet") or query)[:240]],
        "source": source,
        "real": True,
        "industry": data.get("industry"),
        "location": data.get("location") or data.get("city"),
    }


def _prospect_from_web_result(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    title = str(item.get("title") or item.get("Text") or f"Result {index + 1}").strip()[:160]
    snippet = str(item.get("snippet") or item.get("Text") or "").strip()[:240]
    url = str(item.get("url") or item.get("FirstURL") or "").strip()
    domain = None
    if url.startswith("http"):
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc.removeprefix("www.")[:160] or None
        except Exception:
            domain = None
    company = title.split(" - ")[0].split(" | ")[0].strip()[:160] or title
    return {
        "prospect_id": f"web:{index}:{company}"[:80],
        "company": company,
        "domain": domain,
        "signals": [s for s in [snippet, url] if s],
        "source": "public_search",
        "real": bool(item.get("real", True)),
        "url": url or None,
    }


def web_research(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebResearchInput.model_validate(invocation.input)
    store = resolve_record_store(context)
    # Research targets are only what the caller supplied. Never fill a missing
    # company/domain half from the tenant profile (e.g. company=Acme must not
    # get domain=ajenda.ai). Profile values are separate lineage fields.
    # When neither half is explicit, open-query research may surface profile
    # company/domain as the tenant context defaults (demo / self-context path).
    explicit_company = (payload.company or "").strip() or None
    explicit_domain = (payload.domain or "").strip() or None
    profile_company_raw, profile_domain_raw = default_company_and_domain(context=context)
    profile_company = (profile_company_raw or "").strip() or None
    profile_domain = (profile_domain_raw or "").strip() or None
    if explicit_company is not None or explicit_domain is not None:
        company = explicit_company
        domain = explicit_domain
    else:
        company = profile_company
        domain = profile_domain
    search_company = explicit_company or payload.query
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
    if search_domain or search_company:
        internal_matches.extend(
            store.search_records(
                tenant_id=context.tenant_id,
                record_type="contact",
                query=search_domain or search_company,
                limit=payload.limit,
            )
        )

    web_snippet: dict[str, Any] | None = None
    if payload.fetch_public_page and search_domain:
        web_snippet = _fetch_public_page_snippet(
            domain=search_domain,
            action_name="web.research",
            timeout_seconds=payload.timeout_seconds,
        )

    crm_search = default_crm_client().search(
        context=context,
        company=search_company,
        domain=search_domain or "",
        credential=None,
        invocation=invocation,
        action_name="web.research",
    )

    web_results: list[dict[str, Any]] = []
    search_error: str | None = None
    public_search_real = False
    side_effect = SideEffectClass.INTERNAL_READ
    if payload.include_public_search:
        side_effect = SideEffectClass.EXTERNAL_READ
        search_bundle = _fetch_duckduckgo_instant_answer(
            query=payload.query,
            limit=payload.limit,
            timeout_seconds=payload.timeout_seconds,
        )
        raw_results = search_bundle.get("results") or []
        if isinstance(raw_results, list):
            web_results = [item for item in raw_results if isinstance(item, dict)]
        public_search_real = bool(search_bundle.get("real"))
        err = search_bundle.get("error")
        search_error = str(err) if err else None

    prospect_candidates: list[dict[str, Any]] = []
    seen_companies: set[str] = set()
    for record in internal_matches + list(crm_search.results or []):
        if not isinstance(record, dict):
            continue
        prospect = _prospect_from_record(record, source="internal_record", query=payload.query)
        key = prospect["company"].lower()
        if key in seen_companies:
            continue
        seen_companies.add(key)
        prospect_candidates.append(prospect)
        if len(prospect_candidates) >= payload.limit:
            break
    if len(prospect_candidates) < payload.limit:
        for index, item in enumerate(web_results):
            prospect = _prospect_from_web_result(item, index=index)
            key = prospect["company"].lower()
            if key in seen_companies:
                continue
            seen_companies.add(key)
            prospect_candidates.append(prospect)
            if len(prospect_candidates) >= payload.limit:
                break

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
        "web_results": web_results[: payload.limit],
        "web_result_count": len(web_results),
        "web_snippet": web_snippet,
        "include_public_search": payload.include_public_search,
        "public_search_real": public_search_real,
        "search_error": search_error,
        "access_mode": "public_search" if payload.include_public_search else "internal_research",
        "business_context_source": business_context.source,
        "source": "ajenda_brain",
        # Operation completed through a legitimate research path (internal and/or public).
        "real": True,
        # Whether returned candidates themselves are real-world entities.
        "candidates_real": bool(prospect_candidates) and all(bool(p.get("real", True)) for p in prospect_candidates),
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


def register_standalone_actions(registry: ActionRegistry) -> None:
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
