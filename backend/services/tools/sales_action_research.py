"""Sales research and observed-contact normalization."""

from typing import Any

from backend.services.business_profile.context_resolver import default_company_and_domain
from backend.services.plugins.crm_client import default_crm_client, is_live_external_crm_result
from backend.services.tools.sales_action_common import _evidence, _provider
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    RuntimeCredentialMaterial,
    SalesLeadInput,
    SideEffectClass,
    ToolInvocation,
)


def sales_research(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    context_map = payload.context if isinstance(payload.context, dict) else {}
    bound_prospects = [dict(item) for item in (context_map.get("prospect_candidates") or []) if isinstance(item, dict)]
    targets = bound_prospects or [dict(payload.lead)]
    require_external_crm = bool(context_map.get("require_external_crm"))

    cred: RuntimeCredentialMaterial | dict[str, Any] | None = context.runtime_credentials.get(
        "sales.research"
    ) or context.runtime_credentials.get("crm.research")
    attempted_external = invocation.credential_reference is not None or cred is not None

    researched_prospects: list[dict[str, Any]] = []
    related_records: list[dict[str, Any]] = []
    crm_matches: list[dict[str, Any]] = []
    research_notes: list[str] = []
    inspected: list[str] = []
    sources: list[str] = []
    status_codes: list[int] = []
    any_external = False
    any_external_attempt_failed = False

    for target in targets:
        account_id = str(target.get("account_id") or (payload.account_id if not bound_prospects else "") or "")
        related: list[dict[str, Any]] = []
        if account_id:
            account = _provider(context).read_record(
                tenant_id=context.tenant_id, record_type="account", record_id=account_id
            )
            if account:
                related.append(account)

        if bound_prospects:
            # Bound prospect identity is authoritative for this job. Never fall back
            # to the tenant business profile when researching an upstream prospect.
            company = str(target.get("company") or target.get("name") or "").strip()
            domain = str(target.get("domain") or "").strip() or None
            if not company and not domain:
                raise ValueError(
                    "sales.research requires each bound prospect to provide company/name or domain; "
                    "refusing tenant-profile substitution"
                )
        else:
            company, domain = default_company_and_domain(
                context=context,
                company=str(target.get("company", "") or ""),
                domain=str(target.get("domain", "") or "") or None,
            )

        search = default_crm_client().search(
            context=context,
            company=company,
            domain=domain or "",
            credential=cred,
            invocation=invocation,
            action_name="sales.research",
        )
        use_external = is_live_external_crm_result(
            source=search.source,
            real=search.real,
            error=search.error,
        )
        external_attempt_failed = bool(attempted_external and search.error)

        # Explicit HubSpot / CRM-read missions must not silently complete on brain fallback.
        if require_external_crm:
            if search.error:
                raise ValueError(
                    f"HubSpot CRM read failed and internal brain fallback is disabled for this mission: {search.error}"
                )
            if not use_external:
                raise ValueError(
                    "HubSpot CRM read required external records but no live HubSpot result was returned; "
                    "refusing Ajenda-brain fallback for explicit CRM read"
                )

        notes = (
            [f"external CRM plugin search via {search.source} (count={search.count})"]
            if use_external
            else [f"Ajenda central brain search (count={search.count})"]
        )
        if external_attempt_failed:
            notes.append(f"external attempt failed: {search.error}; used internal brain fallback")

        researched = {
            **target,
            "crm_matches": search.results,
            "research_notes": notes,
            "research_source": search.source,
            "research_real": True,
            "plugin_required": use_external,
            "hybrid_mode": external_attempt_failed,
        }
        if related:
            researched["related_records"] = related
        if search.status_code is not None:
            researched["research_status_code"] = search.status_code
            status_codes.append(search.status_code)
        researched_prospects.append(researched)

        related_records.extend(related)
        crm_matches.extend(item for item in search.results if isinstance(item, dict))
        research_notes.extend(notes)
        sources.append(search.source)
        any_external = any_external or use_external
        any_external_attempt_failed = any_external_attempt_failed or external_attempt_failed
        inspected.extend(str(item["id"]) for item in related if item.get("id"))
        inspected.extend(str(item["id"]) for item in search.results if isinstance(item, dict) and item.get("id"))

    # Keep the direct-action response shape while emitting the declared discovery
    # artifact consumed by observe/qualify/enrich. The provider payload is
    # normalized from observed CRM properties; no contact or business fact is
    # synthesized when HubSpot did not return it.
    prospect_candidates: list[dict[str, Any]] = []
    for researched in researched_prospects:
        candidate = dict(researched)
        matches = [item for item in (researched.get("crm_matches") or []) if isinstance(item, dict)]
        match = matches[0] if matches else {}
        raw_properties = match.get("properties")
        properties = raw_properties if isinstance(raw_properties, dict) else {}
        provider_id = str(match.get("id") or "").strip()
        company = str(properties.get("name") or candidate.get("company") or "").strip()
        domain = str(properties.get("domain") or candidate.get("domain") or "").strip() or None
        website = str(properties.get("website") or "").strip() or (f"https://{domain}" if domain else None)
        product_description = str(properties.get("description") or "").strip()
        if not product_description:
            product_description = "No product description was provided by HubSpot CRM."
        research_summary = (
            f"Observed HubSpot CRM company record {provider_id or company}. "
            f"Provider properties were read through the governed CRM adapter."
        )
        source_reference = f"hubspot://companies/{provider_id}" if provider_id else "hubspot://companies/search"
        candidate.update(
            {
                "id": provider_id or candidate.get("id"),
                "prospect_id": provider_id or candidate.get("prospect_id") or company,
                "company": company,
                "domain": domain,
                "website": website,
                "product_description": product_description,
                "research_summary": research_summary,
                "sources": [source_reference],
                "source": "external_crm",
                "research_source": "external_crm",
                "research_real": True,
                "real": True,
                "identity_status": "verified",
                "provider_record_id": provider_id or None,
                "provider_properties": properties,
            }
        )
        if isinstance(match.get("contacts"), list):
            candidate["contacts"] = [item for item in match["contacts"] if isinstance(item, dict)]
        prospect_candidates.append(candidate)

    # Existing single-lead callers remain valid while composed runtime nodes
    # consume the canonical prospect_candidates artifact.
    first_target = targets[0] if targets else {}
    unique_sources = list(dict.fromkeys(sources))
    output: dict[str, Any] = {
        "lead": first_target,
        "related_records": related_records,
        "crm_matches": crm_matches,
        "research_notes": research_notes,
        "researched_prospects": researched_prospects,
        "prospect_candidates": prospect_candidates,
        "real": True,
        "plugin_required": any_external,
        "source": unique_sources[0] if len(unique_sources) == 1 else "mixed",
        "hybrid_mode": any_external_attempt_failed,
    }
    if any_external_attempt_failed:
        output["external_attempt_failed"] = True
    if any_external and cred is not None:
        output["credential_reference"] = {
            "provider": getattr(getattr(cred, "reference", None), "provider", None)
            if not isinstance(cred, dict)
            else cred.get("provider"),
        }
        if len(status_codes) == 1:
            output["real_response"] = {"status_code": status_codes[0]}
        if invocation.idempotency_key:
            output["idempotency_key"] = invocation.idempotency_key

    inspected = list(dict.fromkeys(inspected))
    # ActionResult.provider is the registry owner and must remain the
    # registered ``ajenda_brain`` provider. External HubSpot provenance is
    # carried in the result payload/evidence source fields above.
    provider = "ajenda_brain"
    side_effect_class = (
        SideEffectClass.EXTERNAL_READ if invocation.credential_reference is not None else SideEffectClass.INTERNAL_READ
    )
    summary = f"Researched {len(researched_prospects)} prospect(s) with {len(crm_matches)} CRM match(es)." + (
        " via external plugin" if any_external else " via Ajenda brain"
    )
    confidence = 0.9 if any_external else 0.85
    return ActionResult(
        action="sales.research",
        provider=provider,
        side_effect_class=side_effect_class,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.research",
                provider=provider,
                summary=summary,
                payload=output,
                inspected=inspected,
                side_effect_class=side_effect_class,
                confidence=confidence,
            )
        ],
        records_inspected=inspected,
        summary=summary,
        confidence=confidence,
    )


def _normalize_observed_lead(lead: dict[str, Any]) -> dict[str, Any]:
    """Map observe-contact records onto lead email/phone fields."""

    normalized = dict(lead)
    kind = str(normalized.get("kind") or "").strip().lower()
    value = str(normalized.get("value") or "").strip()
    if kind == "email" and value and not normalized.get("email"):
        normalized["email"] = value
    if kind == "phone" and value and not normalized.get("phone"):
        normalized["phone"] = value
    return normalized


def _is_invented_enrich_contact(lead: dict[str, Any]) -> bool:
    if lead.get("simulated") is True or lead.get("enrichment_mode") == "local_simulated":
        return True
    if str(lead.get("source") or "") == "local_gtm_heuristic":
        return True
    contacts = lead.get("contacts")
    if isinstance(contacts, list):
        for item in contacts:
            if not isinstance(item, dict):
                continue
            if item.get("simulated") is True or str(item.get("source") or "") == "local_gtm_heuristic":
                return True
    return False


def _has_real_contact(lead: dict[str, Any]) -> bool:
    """True only for a caller-supplied or observed mailbox/phone — not search snippets."""

    if _is_invented_enrich_contact(lead):
        return False
    email = str(lead.get("email") or "").strip()
    if email and "@" in email:
        local = email.split("@", 1)[0].lower()
        if local != "contact":
            return True
        if str(lead.get("source") or "") == "local_gtm_heuristic":
            return False
        return True
    if str(lead.get("phone") or "").strip():
        return True
    contacts = lead.get("contacts")
    if isinstance(contacts, list):
        for item in contacts:
            if not isinstance(item, dict):
                continue
            if item.get("real") is True and item.get("simulated") is not True:
                return True
            value = str(item.get("email") or item.get("value") or "").strip()
            if value and "@" in value and item.get("simulated") is not True:
                return True
    return False


def _merge_observed_contacts(
    prospects: list[dict[str, Any]], observed_contacts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach observed contact artifacts to their matching prospect records."""

    if not observed_contacts:
        return prospects
    merged: list[dict[str, Any]] = []
    for prospect in prospects:
        item = dict(prospect)
        identities = {
            str(item.get(key) or "").strip().casefold()
            for key in ("prospect_id", "account_id", "domain", "company", "name")
            if str(item.get(key) or "").strip()
        }
        matches = [
            contact
            for contact in observed_contacts
            if identities
            & {
                str(contact.get(key) or "").strip().casefold()
                for key in ("prospect_id", "account_id", "domain", "company", "name")
                if str(contact.get(key) or "").strip()
            }
        ]
        if matches:
            existing = item.get("observed_contacts")
            prior = existing if isinstance(existing, list) else []
            item["observed_contacts"] = [*prior, *matches]
            for contact in matches:
                kind = str(contact.get("kind") or "").strip().casefold()
                value = str(contact.get("value") or "").strip()
                if contact.get("source_url") and not item.get("source_url"):
                    item["source_url"] = contact["source_url"]
                if kind == "email" and value and not item.get("email"):
                    item["email"] = value
                elif kind == "phone" and value and not item.get("phone"):
                    item["phone"] = value
        merged.append(item)
    return merged
