"""Governed public internet actions: page read, browser session, open write."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from backend.services.internet import InternetAccessMode, fetch_public_page
from backend.services.internet.browser_session import browser_session_as_dict, run_browser_session
from backend.services.internet.open_write import execute_open_write
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.contact_observation import (
    extract_observed_contacts,
    page_host,
    prospect_source_url,
)
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    ResearchObserveContactsInput,
    SideEffectClass,
    ToolInvocation,
    WebBrowserSessionInput,
    WebOpenWriteInput,
    WebPageReadInput,
)


def web_page_read(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebPageReadInput.model_validate(invocation.input)
    snapshot = fetch_public_page(
        url_or_domain=payload.url,
        timeout_seconds=payload.timeout_seconds,
        action_name="web.page_read",
    )
    output = snapshot.as_dict()
    output["access_mode"] = InternetAccessMode.PAGE_READ.value
    output["related_modes"] = {
        "browser_session": "web.browser_session (flag AJENDA_BROWSER_SESSION_ENABLED)",
        "open_write": "web.open_write (flag AJENDA_OPEN_WRITE_ENABLED)",
    }
    real = bool(output.get("real"))
    title = output.get("title") or ""
    summary = (
        f"Read public page {output.get('url')} (status={output.get('status_code')}, title={title[:80]!r}, real={real})."
        if real
        else f"Public page read failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.page_read",
        action_name="web.page_read",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title"),
            "real": real,
            "access_mode": InternetAccessMode.PAGE_READ.value,
            "browser_ready": False,
        },
        confidence=0.9 if real else 0.4,
        limitations=[
            "single HTTPS GET only — no JavaScript execution",
            "redirects disabled by NetworkEgressAuthority",
            "response body bounded; HTML extraction is best-effort",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet.page_read",
            "access_mode": InternetAccessMode.PAGE_READ.value,
        },
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="web.page_read",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.9 if real else 0.4,
    )


def web_browser_session(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebBrowserSessionInput.model_validate(invocation.input)
    snapshot = run_browser_session(
        url_or_domain=payload.url,
        timeout_seconds=payload.timeout_seconds,
        wait_until=payload.wait_until,
        extract_text=payload.extract_text,
    )
    output = browser_session_as_dict(snapshot)
    real = bool(output.get("real"))
    title = output.get("title") or ""
    summary = (
        f"Browser session {output.get('url')} (status={output.get('status_code')}, title={title[:80]!r}, real={real})."
        if real
        else f"Browser session failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.browser_session",
        action_name="web.browser_session",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "status_code": output.get("status_code"),
            "title": output.get("title"),
            "real": real,
            "access_mode": InternetAccessMode.BROWSER_SESSION.value,
            "ephemeral": True,
            "browser_ready": output.get("browser_ready"),
        },
        confidence=0.85 if real else 0.35,
        limitations=[
            "requires AJENDA_BROWSER_SESSION_ENABLED=true",
            "ephemeral Playwright context destroyed after each call",
            "URL vetted by NetworkEgressAuthority before navigation",
            "not a multi-step agent loop — single navigate extract",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "internet_access": "backend.services.internet.browser_session",
            "access_mode": InternetAccessMode.BROWSER_SESSION.value,
            "tenant_isolation": "single_use_context",
        },
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="web.browser_session",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.85 if real else 0.35,
    )


def web_open_write(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = WebOpenWriteInput.model_validate(invocation.input)
    # Rate limit is tenant-scoped inside execute_open_write (never worker_id).
    result = execute_open_write(
        tenant_id=context.tenant_id,
        url=payload.url,
        method=payload.method,
        idempotency_key=payload.idempotency_key,
        json_body=payload.json_body,
        body_text=payload.body_text,
        headers=payload.headers,
        timeout_seconds=payload.timeout_seconds,
        session_factory=context.session_factory,
    )
    output = result.as_dict()
    output["idempotency_key_present"] = True
    real = bool(output.get("real"))
    summary = (
        f"Open write {payload.method} {payload.url} status={output.get('status_code')} real={real}."
        if real
        else f"Open write blocked/failed for {payload.url}: {output.get('error') or 'unknown error'}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.web.open_write",
        action_name="web.open_write",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "url": output.get("url"),
            "method": output.get("method"),
            "status_code": output.get("status_code"),
            "real": real,
            "access_mode": InternetAccessMode.OPEN_WRITE.value,
            "rate_limit_remaining": output.get("rate_limit_remaining"),
        },
        confidence=0.8 if real else 0.3,
        limitations=[
            "requires AJENDA_OPEN_WRITE_ENABLED=true",
            "per-tenant hourly rate limit (AJENDA_OPEN_WRITE_MAX_PER_HOUR)",
            "idempotency_key required",
            "HTTPS-only via NetworkEgressAuthority; no credential headers",
        ],
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ToolRuntimeAuthority -> ActionRegistry",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet.open_write",
            "access_mode": InternetAccessMode.OPEN_WRITE.value,
        },
        side_effect_class=SideEffectClass.EXTERNAL_WRITE,
    )
    return ActionResult(
        action="web.open_write",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        output=output,
        evidence=[evidence],
        summary=summary,
        confidence=0.8 if real else 0.3,
    )


def research_observe_contacts(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = ResearchObserveContactsInput.model_validate(invocation.input)
    raw_prospects = [item for item in payload.prospects if isinstance(item, dict)]
    if payload.binding_required and not raw_prospects:
        raise ValueError("research.observe_contacts requires bound prospect_candidates")

    seen_urls: set[str] = set()
    duplicate_url_count = 0
    pages: list[dict[str, object]] = []
    observed_contacts: list[dict[str, object]] = []
    unobserved: list[dict[str, object]] = []
    limit = payload.requested_quantity

    for prospect in raw_prospects:
        if len(pages) >= limit:
            break
        url = prospect_source_url(prospect)
        if payload.local_fixture_only:
            fixture_contacts: list[dict[str, object]] = []
            for key, kind in (
                ("email", "email"),
                ("phone", "phone"),
                ("contact_email", "email"),
                ("contact_phone", "phone"),
            ):
                value = prospect.get(key)
                if isinstance(value, str) and value.strip():
                    fixture_contacts.append(
                        {
                            "kind": kind,
                            "value": value.strip(),
                            "source_url": f"fixture://{prospect.get('prospect_id') or prospect.get('company')}",
                            "real": True,
                            "via": "local_fixture",
                        }
                    )
            if not fixture_contacts:
                unobserved.append(
                    {
                        "company": prospect.get("company"),
                        "reason": "no_contact_in_local_fixture",
                        "prospect_id": prospect.get("prospect_id"),
                    }
                )
                continue
            source_url = str(fixture_contacts[0]["source_url"])
            pages.append(
                {
                    "url": source_url,
                    "real": True,
                    "status_code": None,
                    "title": prospect.get("company"),
                    "error": None,
                    "company": prospect.get("company"),
                    "domain": prospect.get("domain"),
                    "identity_status": "verified",
                    "source_reliability": "local_fixture",
                    "identity_evidence_urls": [],
                }
            )
            for item in fixture_contacts:
                observed_contacts.append(
                    {
                        **item,
                        "company": prospect.get("company"),
                        "domain": prospect.get("domain"),
                        "website": str(prospect.get("website") or prospect.get("url") or ""),
                        "product_description": str(prospect.get("product_description") or ""),
                        "research_summary": str(prospect.get("research_summary") or ""),
                        "sources": prospect.get("sources") if isinstance(prospect.get("sources"), list) else [],
                        "prospect_id": prospect.get("prospect_id"),
                        "identity_status": "verified",
                        "identity_evidence_urls": [],
                        "contact_role_status": "verified" if prospect.get("role") else "unverified",
                        "contact_role_evidence": "bound prospect role" if prospect.get("role") else None,
                    }
                )
            continue
        if url is None:
            unobserved.append(
                {
                    "company": prospect.get("company"),
                    "reason": "no_url",
                    "prospect_id": prospect.get("prospect_id"),
                }
            )
            continue
        if url in seen_urls:
            duplicate_url_count += 1
            continue
        seen_urls.add(url)
        snapshot = fetch_public_page(
            url_or_domain=url,
            timeout_seconds=payload.timeout_seconds,
            action_name="research.observe_contacts",
            text_preview_chars=8000,
        )
        page_record: dict[str, object] = {
            "url": snapshot.url,
            "real": snapshot.real,
            "status_code": snapshot.status_code,
            "title": snapshot.title,
            "error": snapshot.error,
            "company": prospect.get("company"),
            "domain": prospect.get("domain") or page_host(snapshot.url),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        expected_host = str(prospect.get("domain") or "").lower().removeprefix("www.").split("/")[0]
        actual_host = page_host(snapshot.url)
        company_tokens = [
            token.lower()
            for token in re.findall(r"[a-z0-9]{3,}", str(prospect.get("company") or ""))
            if token.lower() not in {"the", "and", "inc", "llc", "company", "companies"}
        ]
        page_text = " ".join(
            part for part in (snapshot.title, snapshot.text_preview, snapshot.body_preview) if isinstance(part, str)
        ).lower()
        host_matches = bool(
            expected_host
            and actual_host
            and (actual_host == expected_host or actual_host.endswith(f".{expected_host}"))
        )
        directory_host = any(
            marker in actual_host
            for marker in ("directory", "yelp.", "yellowpages", "facebook.", "linkedin.", "instagram.", "maps.")
        )
        company_matches = bool(company_tokens) and any(token in page_text for token in company_tokens)
        identity_status = (
            "verified"
            if host_matches and not directory_host and (company_matches or len(company_tokens) <= 1)
            else "unverified"
        )
        page_record["identity_status"] = identity_status
        page_record["source_reliability"] = (
            "official" if host_matches and not directory_host else "directory_or_third_party"
        )
        page_record["identity_evidence_urls"] = [snapshot.url] if identity_status == "verified" else []
        pages.append(page_record)
        if not snapshot.real:
            unobserved.append({**page_record, "reason": snapshot.error or "page_fetch_failed"})
            continue
        if identity_status != "verified":
            # Directory pages may contain convincing contact data, but they do
            # not establish which individual company that data belongs to.
            # Preserve the page as evidence while refusing to promote contacts
            # from an unresolved public identity.
            unobserved.append({**page_record, "reason": "identity_unverified"})
            continue
        haystack = " ".join(
            part
            for part in (snapshot.title, snapshot.text_preview, snapshot.body_preview)
            if isinstance(part, str) and part
        )
        extracted = extract_observed_contacts(text=haystack, source_url=snapshot.url)
        if not extracted:
            unobserved.append({**page_record, "reason": "no_contact_on_page"})
            continue

        raw_sources = prospect.get("sources")
        sources = [
            str(source).strip()[:500]
            for source in (raw_sources if isinstance(raw_sources, list) else [])
            if isinstance(source, str) and source.strip()
        ]
        if snapshot.url and snapshot.url not in sources:
            sources.append(snapshot.url[:500])
        research_summary = prospect.get("research_summary")
        if not isinstance(research_summary, str) or not research_summary.strip():
            raw_signals = prospect.get("signals")
            signals = (
                [str(signal).strip() for signal in raw_signals if isinstance(signal, str) and signal.strip()]
                if isinstance(raw_signals, list)
                else []
            )
            research_summary = " ".join(signals)
        product_description = prospect.get("product_description")
        if not isinstance(product_description, str):
            product_description = ""
        website = str(prospect.get("website") or prospect.get("url") or snapshot.url or "").strip()

        for item in extracted:
            observed_contacts.append(
                {
                    **item,
                    "company": prospect.get("company"),
                    "domain": page_record["domain"],
                    "website": website[:500],
                    "product_description": product_description.strip()[:1000],
                    "research_summary": research_summary.strip()[:1000],
                    "sources": sources,
                    "prospect_id": prospect.get("prospect_id"),
                    "identity_status": identity_status,
                    "identity_evidence_urls": page_record["identity_evidence_urls"],
                    "contact_role_status": "verified" if prospect.get("role") else "unverified",
                    "contact_role_evidence": "bound prospect role" if prospect.get("role") else None,
                }
            )

    unique_urls_with_real = {str(item["source_url"]) for item in observed_contacts if item.get("real") is True}
    accept_met = len(unique_urls_with_real) >= limit
    limitations = [
        "contacts are extracted from fetched HTML text only",
        "page locality is not verified",
        "javascript-only contact widgets are unobserved",
    ]
    output = {
        "prospect_candidates": [
            {
                **prospect,
                "identity_status": next(
                    (
                        str(page.get("identity_status"))
                        for page in pages
                        if page.get("company") == prospect.get("company") and page.get("identity_status")
                    ),
                    prospect.get("identity_status", "unverified"),
                ),
                "identity_evidence_urls": next(
                    (
                        page.get("identity_evidence_urls")
                        for page in pages
                        if page.get("company") == prospect.get("company") and page.get("identity_evidence_urls")
                    ),
                    prospect.get("identity_evidence_urls", []),
                ),
            }
            for prospect in raw_prospects
        ],
        "observed_contacts": observed_contacts,
        "observed_count": len(unique_urls_with_real),
        "contact_value_count": len(observed_contacts),
        "unobserved": unobserved,
        "pages": pages,
        "requested_quantity": limit,
        "accept_met": accept_met,
        "real": bool(observed_contacts),
        "limitations": limitations,
        "condition_observations": [
            {
                "condition_key": item["kind"],
                "value": item["value"],
                "source_url": item["source_url"],
                "real": True,
            }
            for item in observed_contacts
        ],
        "evidence_quality": {
            "deduplication": {
                "input_count": len(raw_prospects),
                "unique_source_count": len(seen_urls),
                "duplicate_source_count": duplicate_url_count,
                "status": "complete",
            },
            "source_freshness": {
                "status": "captured",
                "field": "pages[].fetched_at",
            },
            "source_reliability": {
                "status": "classified",
                "field": "pages[].source_reliability",
            },
            "contact_role_verification": {
                "status": "verified_or_unverified",
                "field": "observed_contacts[].contact_role_status",
            },
            "rejection_reasons": [
                {"company": item.get("company"), "reason": item.get("reason")} for item in unobserved
            ],
        },
    }
    summary = (
        f"Observed contacts on {len(unique_urls_with_real)}/{limit} source page(s); "
        f"{len(unobserved)} unobserved; accept_met={accept_met}."
    )
    evidence = EvidenceItem(
        evidence_type="action_result",
        evidence_source="tool.invoke.research.observe_contacts",
        action_name="research.observe_contacts",
        tool_provider="ajenda_internet",
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id else None,
        summary=summary,
        structured_payload={
            "observed_count": output["observed_count"],
            "requested_quantity": limit,
            "accept_met": accept_met,
            "unobserved_count": len(unobserved),
            "condition_observations": output["condition_observations"],
        },
        records_inspected=[str(page.get("url")) for page in pages if page.get("url")],
        records_changed=[],
        confidence=0.85 if accept_met else 0.55,
        limitations=list(limitations),
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> research.observe_contacts",
            "network_egress_authority": "backend.services.network_egress.NetworkEgressAuthority",
            "internet_access": "backend.services.internet.page_read",
        },
        lineage=EvidenceLineage(
            artifact_evidence_id=f"observe-contacts:{context.task_id}",
            origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
            source_identity=(
                EvidenceSourceIdentity(
                    source_system="public_page",
                    source_record_id=next(iter(unique_urls_with_real)),
                )
                if unique_urls_with_real
                else None
            ),
            resolution=(
                EvidenceLineageResolution.KNOWN if unique_urls_with_real else EvidenceLineageResolution.UNKNOWN
            ),
        ),
        side_effect_class=SideEffectClass.EXTERNAL_READ,
    )
    return ActionResult(
        action="research.observe_contacts",
        provider="ajenda_internet",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        output=output,
        evidence=[evidence],
        records_inspected=[str(page.get("url")) for page in pages if page.get("url")],
        summary=summary,
        confidence=0.85 if accept_met else 0.55,
    )


def register_web_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="web.page_read",
            handler=web_page_read,
            provider="ajenda_internet",
            input_model=WebPageReadInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="research.observe_contacts",
            handler=research_observe_contacts,
            provider="ajenda_internet",
            input_model=ResearchObserveContactsInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.browser_session",
            handler=web_browser_session,
            provider="ajenda_internet",
            input_model=WebBrowserSessionInput,
            side_effect_class=SideEffectClass.EXTERNAL_READ,
        )
    )
    registry.register(
        ActionDefinition(
            name="web.open_write",
            handler=web_open_write,
            provider="ajenda_internet",
            input_model=WebOpenWriteInput,
            side_effect_class=SideEffectClass.EXTERNAL_WRITE,
        )
    )
