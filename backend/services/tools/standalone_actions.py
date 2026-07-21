"""Standalone Ajenda brain actions that do not require external CRM plugins."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from backend.services.business_context_resolver import resolve_business_context
from backend.services.network_egress import get_default_network_egress_authority
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

DDG_INSTANT_ANSWER_HOST = "api.duckduckgo.com"


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
        provenance={"runtime_path": "TaskDispatcher -> tool.invoke -> ajenda_brain"},
        side_effect_class=side_effect_class,
    )


def _fetch_public_page_snippet(
    *,
    domain: str,
    action_name: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    page_url = f"https://{domain.lstrip('.')}/"
    try:
        _dest, response = get_default_network_egress_authority().request(
            method="GET",
            url=page_url,
            headers={"User-Agent": "AjendaBrain/1.0"},
            allowed_hosts=[domain.lstrip(".")],
            action_name=action_name,
            timeout_seconds=min(timeout_seconds, 10.0),
        )
        return {
            "url": page_url,
            "status_code": response.status_code,
            "body_preview": (response.body_text or "")[:500],
            "body_truncated": response.body_truncated,
            "real": True,
        }
    except Exception as exc:
        return {"url": page_url, "error": str(exc), "real": False}


def _append_ddg_topic_result(
    results: list[dict[str, Any]],
    *,
    item: dict[str, Any],
    limit: int,
    source: str,
) -> None:
    if len(results) >= limit:
        return
    text = item.get("Text")
    first_url = item.get("FirstURL")
    if not isinstance(text, str) or not text.strip():
        return
    title = text.strip().split(" - ", 1)[0][:160]
    results.append(
        {
            "title": title,
            "snippet": text.strip(),
            "url": first_url if isinstance(first_url, str) else None,
            "source": source,
        }
    )


def _collect_ddg_topics(
    items: object,
    *,
    results: list[dict[str, Any]],
    limit: int,
    source: str,
) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if len(results) >= limit:
            break
        if not isinstance(item, dict):
            continue
        nested = item.get("Topics")
        if isinstance(nested, list):
            _collect_ddg_topics(nested, results=results, limit=limit, source=source)
            continue
        _append_ddg_topic_result(results, item=item, limit=limit, source=source)


def _fetch_duckduckgo_instant_answer(*, query: str, limit: int, timeout_seconds: float) -> dict[str, Any]:
    encoded_query = quote(query.strip())
    search_url = f"https://{DDG_INSTANT_ANSWER_HOST}/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
    try:
        _dest, response = get_default_network_egress_authority().request(
            method="GET",
            url=search_url,
            headers={"User-Agent": "AjendaBrain/1.0"},
            allowed_hosts=[DDG_INSTANT_ANSWER_HOST],
            action_name="web.search",
            timeout_seconds=min(timeout_seconds, 15.0),
            response_text_limit=131_072,
        )
        if response.status_code >= 400:
            return {
                "provider": "duckduckgo_instant_answer",
                "error": f"HTTP {response.status_code}",
                "real": False,
                "results": [],
            }
        if response.body_truncated:
            return {
                "provider": "duckduckgo_instant_answer",
                "error": "response truncated before JSON parse",
                "real": False,
                "results": [],
            }
        payload = json.loads(response.body_text or "{}")
        if not isinstance(payload, dict):
            return {
                "provider": "duckduckgo_instant_answer",
                "error": "non-object JSON response",
                "real": False,
                "results": [],
            }
        results: list[dict[str, Any]] = []
        abstract = payload.get("AbstractText")
        abstract_url = payload.get("AbstractURL")
        if isinstance(abstract, str) and abstract.strip():
            results.append(
                {
                    "title": payload.get("Heading") or query,
                    "snippet": abstract.strip(),
                    "url": abstract_url if isinstance(abstract_url, str) else None,
                    "source": payload.get("AbstractSource"),
                }
            )
        _collect_ddg_topics(
            payload.get("Results"),
            results=results,
            limit=limit,
            source="duckduckgo_results",
        )
        _collect_ddg_topics(
            payload.get("RelatedTopics"),
            results=results,
            limit=limit,
            source="duckduckgo_related",
        )
        return {
            "provider": "duckduckgo_instant_answer",
            "status_code": response.status_code,
            "real": True,
            "results": results[:limit],
            "result_count": len(results[:limit]),
        }
    except Exception as exc:
        return {
            "provider": "duckduckgo_instant_answer",
            "error": str(exc),
            "real": False,
            "results": [],
        }


def _prospect_from_record(record: dict[str, Any], *, source: str, query: str) -> dict[str, Any]:
    data = record.get("data") if isinstance(record.get("data"), dict) else record
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
    # Prefer explicit company from input; do not silently replace market research
    # with the tenant's own business profile domain.
    company = (payload.company or "").strip() or None
    domain = (payload.domain or "").strip() or None
    search_company = company or payload.query

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
    if domain or search_company:
        internal_matches.extend(
            store.search_records(
                tenant_id=context.tenant_id,
                record_type="contact",
                query=domain or search_company,
                limit=payload.limit,
            )
        )

    web_snippet: dict[str, Any] | None = None
    if payload.fetch_public_page and domain:
        web_snippet = _fetch_public_page_snippet(
            domain=domain,
            action_name="web.research",
            timeout_seconds=payload.timeout_seconds,
        )

    crm_search = default_crm_client().search(
        context=context,
        company=search_company,
        domain=domain,
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
        "business_context_source": business_context.source,
        "source": "ajenda_brain",
        "real": bool(prospect_candidates) and all(p.get("real") for p in prospect_candidates),
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
