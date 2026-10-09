"""Observed-contact research action."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.services.internet import fetch_public_page
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)
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
)
from backend.services.tools.web_action_identity_policy import (
    _host_identity_tokens,
    _identity_tokens,
    _industry_evidence_markers,
    _is_directory_or_third_party_host,
    _is_directory_or_third_party_page,
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
    verified_prospect_candidates: list[dict[str, object]] = []
    unobserved: list[dict[str, object]] = []
    followed_directory_links = 0
    followed_link_hosts: set[str] = set()
    limit = payload.requested_quantity
    page_attempt_limit = min(max(limit * 3, limit), 50)

    for prospect in raw_prospects:
        if len(verified_prospect_candidates) >= limit:
            break
        if len(pages) >= page_attempt_limit:
            break
        url = prospect_source_url(prospect)
        if payload.local_fixture_only:
            internal_crm_source = payload.context.get("source") == "internal_crm"
            fixture_contacts: list[dict[str, object]] = []
            contact_source = "internal_crm" if internal_crm_source else "local_fixture"
            contact_real = internal_crm_source
            raw_contacts = prospect.get("contacts") if internal_crm_source else None
            if isinstance(raw_contacts, list):
                for contact in raw_contacts:
                    if not isinstance(contact, dict):
                        continue
                    for key, kind in (("email", "email"), ("phone", "phone")):
                        value = contact.get(key)
                        if isinstance(value, str) and value.strip():
                            fixture_contacts.append(
                                {
                                    "kind": kind,
                                    "value": value.strip(),
                                    "source_url": f"crm://{contact.get('id') or prospect.get('prospect_id') or prospect.get('company')}",
                                    "real": contact_real,
                                    "via": contact_source,
                                }
                            )
            if not fixture_contacts:
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
                                "source_url": (
                                    f"crm://{prospect.get('prospect_id') or prospect.get('company')}"
                                    if internal_crm_source
                                    else f"fixture://{prospect.get('prospect_id') or prospect.get('company')}"
                                ),
                                "real": contact_real,
                                "via": contact_source,
                            }
                        )
            if not fixture_contacts and internal_crm_source:
                # Tenant-owned CRM identity is already authoritative.  A
                # missing phone/email is an evidence gap for qualification,
                # not a reason to discard the company itself.
                company = prospect.get("company") or prospect.get("name")
                source_url = f"crm://{prospect.get('prospect_id') or prospect.get('id') or company}"
                product_description = str(prospect.get("product_description") or prospect.get("description") or "")
                research_summary = str(
                    prospect.get("research_summary")
                    or prospect.get("automation_opportunity")
                    or product_description
                    or "Tenant-owned internal CRM company record."
                )
                pages.append(
                    {
                        "url": source_url,
                        "real": True,
                        "status_code": None,
                        "title": company,
                        "error": None,
                        "company": company,
                        "domain": prospect.get("domain"),
                        "identity_status": "verified",
                        "source_reliability": "tenant_internal_crm",
                        "identity_evidence_urls": [],
                        "evidence_class": "tenant_internal_crm",
                    }
                )
                verified_prospect_candidates.append(
                    {
                        **prospect,
                        "company": company,
                        "product_description": product_description,
                        "research_summary": research_summary,
                        "real": True,
                        "source": "internal_crm",
                        "identity_status": "verified",
                        "identity_evidence_urls": [],
                        "sources": [],
                        "observed_contacts": [],
                    }
                )
                continue
            if not fixture_contacts:
                unobserved.append(
                    {
                        "company": prospect.get("company"),
                        "reason": "no_contact_in_internal_crm"
                        if internal_crm_source
                        else "no_contact_in_local_fixture",
                        "prospect_id": prospect.get("prospect_id"),
                    }
                )
                continue
            source_url = str(fixture_contacts[0]["source_url"])
            fixture_identity_evidence = [source_url]
            product_description = str(
                prospect.get("product_description")
                or prospect.get("description")
                or prospect.get("automation_opportunity")
                or "Tenant-owned internal CRM company record."
            )
            research_summary = str(
                prospect.get("research_summary")
                or prospect.get("automation_opportunity")
                or product_description
                or "Tenant-owned internal CRM company record."
            )
            pages.append(
                {
                    "url": source_url,
                    "real": contact_real,
                    "status_code": None,
                    "title": prospect.get("company"),
                    "error": None,
                    "company": prospect.get("company"),
                    "domain": prospect.get("domain"),
                    "identity_status": "verified",
                    "source_reliability": "tenant_internal_crm" if internal_crm_source else "local_fixture",
                    "identity_evidence_urls": fixture_identity_evidence,
                    "evidence_class": "tenant_internal_crm" if internal_crm_source else "fixture",
                }
            )
            # Local fixtures are authoritative test data. Promote the
            # observed fixture company into the same verified identity stream
            # used by public research so acceptance never depends on the raw
            # discovery payload.
            verified_prospect_candidates.append(
                {
                    **prospect,
                    "real": contact_real,
                    "source": contact_source,
                    "product_description": product_description,
                    "research_summary": research_summary,
                    "identity_status": "verified",
                    "identity_evidence_urls": fixture_identity_evidence,
                    "evidence_class": "tenant_internal_crm" if internal_crm_source else "fixture",
                    "sources": prospect.get("sources") if isinstance(prospect.get("sources"), list) else [],
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
                        "identity_evidence_urls": fixture_identity_evidence,
                        "evidence_class": "tenant_internal_crm" if internal_crm_source else "fixture",
                        "contact_role_status": "verified" if prospect.get("role") else "unverified",
                        "contact_role_evidence": "bound prospect role" if prospect.get("role") else None,
                    }
                )
            continue
        if str(payload.context.get("source") or "") == "external_crm":
            # Provider-backed CRM observations are already authoritative API
            # observations. Do not route them through public web fetching or
            # synthesize a contact when HubSpot returned none.
            provider_id = str(prospect.get("provider_record_id") or prospect.get("id") or "").strip()
            source_url = (
                f"hubspot://companies/{provider_id}"
                if provider_id
                else f"hubspot://companies/{prospect.get('company') or 'search'}"
            )
            contacts = [item for item in (prospect.get("contacts") or []) if isinstance(item, dict)]
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
                    "source_reliability": "hubspot_crm",
                    "identity_evidence_urls": [source_url],
                    "evidence_class": "external_crm_observation",
                }
            )
            if not contacts:
                unobserved.append(
                    {
                        "company": prospect.get("company"),
                        "reason": "no_contact_in_external_crm",
                        "prospect_id": prospect.get("prospect_id"),
                    }
                )
                continue
            observed_contacts_for_prospect: list[dict[str, object]] = []
            for contact in contacts:
                contact_map = contact if isinstance(contact, dict) else {}
                contact_id = str(contact_map.get("id") or "").strip()
                raw_contact_properties = contact_map.get("properties")
                contact_properties = raw_contact_properties if isinstance(raw_contact_properties, dict) else {}
                email = str(contact_properties.get("email") or contact_map.get("email") or "").strip()
                phone = str(contact_properties.get("phone") or contact_map.get("phone") or "").strip()
                contact_observation = {
                    "id": contact_id or None,
                    "kind": "email" if email else "phone" if phone else "contact",
                    "value": email or phone or contact_id,
                    "email": email or None,
                    "phone": phone or None,
                    "source_url": (f"hubspot://contacts/{contact_id}" if contact_id else source_url),
                    "real": True,
                    "via": "external_crm",
                    "company": prospect.get("company"),
                    "domain": prospect.get("domain"),
                    "website": prospect.get("website"),
                    "product_description": prospect.get("product_description"),
                    "research_summary": prospect.get("research_summary"),
                    "sources": prospect.get("sources") if isinstance(prospect.get("sources"), list) else [],
                    "prospect_id": prospect.get("prospect_id"),
                    "identity_status": "verified",
                    "identity_evidence_urls": [source_url],
                    "evidence_class": "external_crm_observation",
                }
                observed_contacts_for_prospect.append(contact_observation)
                observed_contacts.append(contact_observation)
            verified_prospect_candidates.append(
                {
                    **prospect,
                    "real": True,
                    "source": "external_crm",
                    "identity_status": "verified",
                    "identity_evidence_urls": [source_url],
                    "observed_contacts": observed_contacts_for_prospect,
                    "contacts": observed_contacts_for_prospect,
                    "sources": prospect.get("sources") if isinstance(prospect.get("sources"), list) else [source_url],
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
        directory_host = _is_directory_or_third_party_host(actual_host)
        directory_page = directory_host or _is_directory_or_third_party_page(page_text)
        page_tokens = _identity_tokens(page_text)
        company_matches = bool(company_tokens) and any(token in page_tokens for token in company_tokens)
        host_tokens = _host_identity_tokens(actual_host)
        host_identity_matches = bool(host_tokens) and any(token in page_tokens for token in host_tokens)
        industry_markers = _industry_evidence_markers(
            payload.context.get("industry")
            or prospect.get("industry")
            or prospect.get("research_summary")
            or prospect.get("company")
        )
        industry_evidence = any(marker in page_text for marker in industry_markers)
        locality_evidence = any(marker in page_text for marker in ("dallas", "dfw", "texas", " tx "))
        identity_status = (
            "verified"
            if host_matches
            and not directory_page
            and industry_evidence
            and locality_evidence
            and (company_matches or host_identity_matches or len(company_tokens) <= 1)
            else "unverified"
        )
        page_record["identity_status"] = identity_status
        page_record["source_reliability"] = (
            "official" if host_matches and not directory_page else "directory_or_third_party"
        )
        page_record["identity_evidence_urls"] = [snapshot.url] if identity_status == "verified" else []
        pages.append(page_record)
        if not snapshot.real:
            unobserved.append({**page_record, "reason": snapshot.error or "page_fetch_failed"})
            continue
        if identity_status != "verified":
            # Directory pages may contain convincing contact data, but they do
            # not establish which individual company that data belongs to.
            # Follow only bounded external HTTPS links from the page, then run
            # the same host/name check against each linked page. Directory
            # hosts and generic labels remain unresolved.
            links = snapshot.extraction.get("links", []) if isinstance(snapshot.extraction, dict) else []
            source_host = page_host(snapshot.url)
            # Directory pages commonly place the actual company links after
            # navigation and advertising links.  Inspect a bounded prefix of
            # the extracted links; the global host cap still limits network
            # work and prevents an untrusted page from turning this into a
            # crawler.
            for link in links[:50] if isinstance(links, list) else []:
                if followed_directory_links >= limit * 3:
                    break
                if not isinstance(link, dict):
                    continue
                linked_url = link.get("url")
                label = str(link.get("text") or "").strip()
                if not isinstance(linked_url, str) or not linked_url.startswith("https://") or not label:
                    continue
                linked_host = page_host(linked_url)
                if (
                    not linked_host
                    or linked_host == source_host
                    or any(marker in linked_host for marker in _DIRECTORY_HOST_MARKERS)
                ):
                    continue
                if linked_host in followed_link_hosts:
                    continue
                followed_link_hosts.add(linked_host)
                followed_directory_links += 1
                linked_snapshot = fetch_public_page(
                    url_or_domain=linked_url,
                    timeout_seconds=payload.timeout_seconds,
                    action_name="research.observe_contacts",
                    text_preview_chars=8000,
                )
                linked_text = " ".join(
                    part
                    for part in (linked_snapshot.title, linked_snapshot.text_preview, linked_snapshot.body_preview)
                    if isinstance(part, str)
                ).lower()
                linked_actual_host = page_host(linked_snapshot.url)
                linked_title = str(linked_snapshot.title or "").strip()
                generic_link_label = label.lower() in {
                    "website",
                    "visit website",
                    "learn more",
                    "view website",
                    "view profile",
                    "get details",
                    "read more",
                }
                identity_label = linked_title if generic_link_label and linked_title else label
                tokens = [
                    token.lower()
                    for token in re.findall(r"[a-z0-9]{3,}", identity_label)
                    if token.lower() not in {"the", "and", "inc", "llc", "company", "companies", "website", "home"}
                ]
                host_tokens = _host_identity_tokens(linked_actual_host)
                identity_text_match = bool(tokens) and any(token in linked_text for token in tokens)
                host_text_match = bool(host_tokens) and any(token in linked_text for token in host_tokens)
                industry_text_match = any(marker in linked_text for marker in industry_markers)
                locality_text_match = any(marker in linked_text for marker in ("dallas", "dfw", "texas", " tx "))
                if (
                    not linked_snapshot.real
                    or linked_actual_host != linked_host
                    or not industry_text_match
                    or not locality_text_match
                    or not (identity_text_match or host_text_match)
                ):
                    continue
                company_label = identity_label[:240] or linked_host
                candidate = {
                    **prospect,
                    "prospect_id": f"web:resolved:{linked_host}",
                    "company": company_label,
                    "domain": linked_host,
                    "website": linked_snapshot.url,
                    "url": linked_snapshot.url,
                    "source": "public_search",
                    "real": True,
                    "identity_status": "verified",
                    "identity_evidence_urls": [snapshot.url, linked_snapshot.url],
                    "sources": [snapshot.url, linked_snapshot.url],
                    "research_summary": " ".join(
                        part for part in (linked_snapshot.title, linked_snapshot.text_preview) if isinstance(part, str)
                    )[:1000],
                    "observed_contacts": [],
                }
                verified_prospect_candidates.append(candidate)
                extracted = extract_observed_contacts(
                    text=" ".join(
                        part
                        for part in (linked_snapshot.title, linked_snapshot.text_preview, linked_snapshot.body_preview)
                        if isinstance(part, str)
                    ),
                    source_url=linked_snapshot.url,
                )
                for item in extracted:
                    contact = {
                        **item,
                        "company": candidate["company"],
                        "domain": linked_host,
                        "website": linked_snapshot.url,
                        "product_description": candidate.get("product_description", ""),
                        "research_summary": candidate["research_summary"],
                        "sources": candidate["sources"],
                        "prospect_id": candidate.get("prospect_id"),
                        "identity_status": "verified",
                        "identity_evidence_urls": candidate["identity_evidence_urls"],
                    }
                    observed_contacts.append(contact)
                    candidate["observed_contacts"].append(contact)
                if not extracted:
                    contact = {
                        "kind": None,
                        "value": None,
                        "source_url": linked_snapshot.url,
                        "real": True,
                        "company": candidate["company"],
                        "domain": linked_host,
                        "website": linked_snapshot.url,
                        "research_summary": candidate["research_summary"],
                        "sources": candidate["sources"],
                        "prospect_id": candidate.get("prospect_id"),
                        "identity_status": "verified",
                        "identity_evidence_urls": candidate["identity_evidence_urls"],
                    }
                    observed_contacts.append(contact)
                    candidate["observed_contacts"].append(contact)
                if len(verified_prospect_candidates) >= limit:
                    break
            unobserved.append({**page_record, "reason": "identity_unverified"})
            continue
        haystack = " ".join(
            part
            for part in (snapshot.title, snapshot.text_preview, snapshot.body_preview)
            if isinstance(part, str) and part
        )
        raw_sources = prospect.get("sources")
        sources = [
            str(source).strip()[:500]
            for source in (raw_sources if isinstance(raw_sources, list) else [])
            if isinstance(source, str) and source.strip()
        ]
        if snapshot.url and snapshot.url not in sources:
            sources.append(snapshot.url[:500])
        extracted = extract_observed_contacts(text=haystack, source_url=snapshot.url)
        if not extracted:
            if identity_status == "verified":
                # Identity verification is independent of contact extraction.
                # A real official company page remains a verified prospect even
                # when its contact details are absent or rendered by JavaScript.
                raw_research_summary = prospect.get("research_summary")
                research_summary = raw_research_summary if isinstance(raw_research_summary, str) else ""
                if not research_summary.strip():
                    raw_signals = prospect.get("signals")
                    signals = (
                        [str(signal).strip() for signal in raw_signals if isinstance(signal, str) and signal.strip()]
                        if isinstance(raw_signals, list)
                        else []
                    )
                    research_summary = " ".join(signals)
                raw_product_description = prospect.get("product_description")
                product_description = raw_product_description if isinstance(raw_product_description, str) else ""
                website = str(prospect.get("website") or prospect.get("url") or snapshot.url or "").strip()
                verified_prospect_candidates.append(
                    {
                        **prospect,
                        "website": website[:500],
                        "real": True,
                        "identity_status": "verified",
                        "identity_evidence_urls": page_record["identity_evidence_urls"],
                        "sources": sources,
                        "research_summary": research_summary.strip()[:1000],
                        "product_description": product_description.strip()[:1000],
                        "observed_contacts": [],
                    }
                )
                observed_contacts.append(
                    {
                        "kind": None,
                        "value": None,
                        "source_url": snapshot.url,
                        "real": True,
                        "company": prospect.get("company"),
                        "domain": page_record["domain"],
                        "website": str(prospect.get("website") or prospect.get("url") or snapshot.url)[:500],
                        "product_description": str(prospect.get("product_description") or "")[:1000],
                        "research_summary": str(prospect.get("research_summary") or "")[:1000],
                        "sources": sources,
                        "prospect_id": prospect.get("prospect_id"),
                        "identity_status": "verified",
                        "identity_evidence_urls": page_record["identity_evidence_urls"],
                    }
                )
                if len(verified_prospect_candidates) >= limit:
                    break
            else:
                unobserved.append({**page_record, "reason": "no_contact_on_page"})
            continue

        raw_research_summary = prospect.get("research_summary")
        research_summary = raw_research_summary if isinstance(raw_research_summary, str) else ""
        if not research_summary.strip():
            raw_signals = prospect.get("signals")
            signals = (
                [str(signal).strip() for signal in raw_signals if isinstance(signal, str) and signal.strip()]
                if isinstance(raw_signals, list)
                else []
            )
            research_summary = " ".join(signals)
        raw_product_description = prospect.get("product_description")
        product_description = raw_product_description if isinstance(raw_product_description, str) else ""
        website = str(prospect.get("website") or prospect.get("url") or snapshot.url or "").strip()

        # A verified official page is itself a verified company artifact. It
        # must be promoted even when the page exposes no phone or email.
        verified_candidate = {
            **prospect,
            "website": website[:500],
            "real": True,
            "identity_status": "verified",
            "identity_evidence_urls": page_record["identity_evidence_urls"],
            "sources": sources,
            "research_summary": research_summary.strip()[:1000],
            "product_description": product_description.strip()[:1000],
            "observed_contacts": [],
        }
        verified_prospect_candidates.append(verified_candidate)

        for item in extracted:
            contact = {
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
            observed_contacts.append(contact)
            verified_candidate["observed_contacts"].append(contact)

        if len(verified_prospect_candidates) >= limit:
            # The requested quantity is a terminal artifact cardinality. Keep
            # the raw page evidence collected so far, but do not promote extra
            # verified rows beyond the operator's requested count.
            break

    accepted_observation_urls = {
        str(item["source_url"])
        for item in observed_contacts
        if item.get("real") is True or item.get("via") == "local_fixture"
    }
    accept_met = len(accepted_observation_urls) >= limit
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
        "verified_prospect_candidates": verified_prospect_candidates,
        "observed_contacts": observed_contacts,
        "observed_count": len(accepted_observation_urls),
        "contact_value_count": len(observed_contacts),
        "unobserved": unobserved,
        "pages": pages,
        "directory_link_resolution": {
            "followed_count": followed_directory_links,
            "unique_hosts": len(followed_link_hosts),
            "max_followed": limit * 3,
            "page_attempt_limit": page_attempt_limit,
        },
        "requested_quantity": limit,
        "accept_met": accept_met,
        "research_gap": (
            "no verified candidates produced; public identity observation rejected all candidate sources"
            if not verified_prospect_candidates
            else None
        ),
        "real": any(item.get("real") is True for item in observed_contacts),
        "limitations": limitations,
        "condition_observations": [
            {
                "condition_key": item["kind"],
                "value": item["value"],
                "source_url": item["source_url"],
                "real": item.get("real") is True,
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
        f"Observed contacts on {len(accepted_observation_urls)}/{limit} source page(s); "
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
                    source_system="fixture_data" if payload.local_fixture_only else "public_page",
                    source_record_id=next(iter(accepted_observation_urls)),
                )
                if accepted_observation_urls
                else None
            ),
            resolution=(
                EvidenceLineageResolution.KNOWN if accepted_observation_urls else EvidenceLineageResolution.UNKNOWN
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
