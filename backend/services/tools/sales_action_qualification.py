"""Sales qualification, scoring, and next-action recommendation."""

from typing import Any

from backend.services.tools.sales_action_common import _evidence
from backend.services.tools.sales_action_research import (
    _has_real_contact,
    _merge_observed_contacts,
    _normalize_observed_lead,
)
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    SalesLeadInput,
    ToolInvocation,
)


def _first_lead_text(*values: Any) -> str:
    """Return explicit lead text without synthesizing missing facts."""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            items = [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
            if items:
                return "; ".join(items)
    return ""

def _lead_source_references(lead: dict[str, Any]) -> list[str]:
    """Preserve explicit source references used by qualification."""

    references: list[str] = []
    raw_sources = lead.get("sources")
    values: list[Any] = list(raw_sources) if isinstance(raw_sources, (list, tuple)) else []
    raw_identity_sources = lead.get("identity_evidence_urls")
    if isinstance(raw_identity_sources, (list, tuple)):
        values.extend(raw_identity_sources)
    values.extend((lead.get("source_url"), lead.get("website"), lead.get("url")))
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in references:
            references.append(normalized[:500])
    return references

def _ajenda_relevance(*, lead: dict[str, Any], context: dict[str, Any]) -> str:
    """Describe relevance only when the inputs contain an automation or intent signal."""

    opportunity = _first_lead_text(
        lead.get("automation_opportunity"),
        lead.get("workflow"),
        context.get("automation_opportunity"),
    )
    if opportunity:
        return f"Ajenda may be relevant to the observed automation opportunity: {opportunity[:500]}."
    intent = _first_lead_text(lead.get("intent"), context.get("intent"))
    if intent:
        return f"Ajenda may be relevant because the observed intent signal identifies a workflow to evaluate: {intent[:500]}."
    return ""

def _qualify_one(lead: dict[str, Any], *, context: dict[str, Any], account_id: str | None) -> dict[str, Any]:
    lead = _normalize_observed_lead(lead)
    fit_points = 0
    reasons: list[str] = []
    if lead.get("company") or account_id:
        fit_points += 35
        reasons.append("company/account context present")
    if lead.get("role") or lead.get("title"):
        fit_points += 25
        reasons.append("buyer role context present")
    if lead.get("intent") or context.get("intent"):
        fit_points += 25
        reasons.append("intent signal present")
    if _has_real_contact(lead):
        fit_points += 15
        reasons.append("contactability present")
    if lead.get("domain") or lead.get("url") or lead.get("signals"):
        fit_points += 15
        reasons.append("research signals present")
    if lead.get("source") == "public_search" or lead.get("source") == "internal_record":
        fit_points += 10
        reasons.append("sourced from research world-state")
    score = min(fit_points, 100)
    provider_record_basis = context.get("provider_source") == "hubspot"
    dimensions = {
        "business_fit": 10
        if (lead.get("company") or account_id)
        and (
            lead.get("industry")
            or lead.get("location")
            or account_id
            or (provider_record_basis and lead.get("identity_status") == "verified")
        )
        else 5
        if (lead.get("company") or account_id)
        else 0,
        "automation_opportunity": 10
        if lead.get("automation_opportunity") or lead.get("workflow") or context.get("automation_opportunity")
        else 5
        if lead.get("intent") or context.get("intent")
        else 0,
        "evidence_quality": 10
        if lead.get("identity_status") == "verified" and (lead.get("source_url") or lead.get("url"))
        else 8
        if lead.get("source") == "internal_record"
        else 4
        if lead.get("signals") or lead.get("source_url") or lead.get("url")
        else 0,
        "urgency": 10 if lead.get("urgency") else 5 if lead.get("intent") or context.get("intent") else 0,
    }
    score_10 = round(sum(dimensions.values()) / len(dimensions))
    mission_scoring = bool(context.get("mission_specific_scoring")) or "qualification_threshold_10" in context
    threshold_10 = int(context.get("qualification_threshold_10", 7) or 7)
    contactable = _has_real_contact(lead)
    identity_verified = (
        lead.get("identity_status") == "verified" or lead.get("source") == "internal_record" or bool(account_id)
    )
    # A composed qualification/ranking stage evaluates the persisted research
    # artifact. Public identity and evidence are sufficient to rank a prospect;
    # contactability is required later by enrichment/send authority. Isolated
    # sales.qualify calls retain the stricter contact gate.
    ranking_only = bool(context.get("ranking_only"))
    qualified = (
        identity_verified
        if ranking_only
        else (
            identity_verified and contactable
            if provider_record_basis
            else (
                score_10 >= threshold_10 and identity_verified
                if mission_scoring
                else contactable and lead.get("identity_status") != "unverified"
            )
        )
    )
    if qualified and provider_record_basis:
        reasons.append("verified HubSpot identity and observed contactability")
    if not qualified and (not contactable or lead.get("identity_status") == "unverified"):
        reasons.append("not qualified without an observed or supplied contact")
    if lead.get("identity_status") == "unverified":
        reasons.append("identity is unverified")
    return {
        "score": score,
        "score_10": score_10,
        "qualification_dimensions": dimensions,
        "qualification_threshold_10": threshold_10,
        "qualified": qualified,
        "reasons": reasons or ["insufficient local qualification signals"],
    }

def sales_qualify(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    prospects_in = [p for p in payload.prospects if isinstance(p, dict)]
    observed_contacts = [dict(item) for item in payload.context.get("observed_contacts", []) if isinstance(item, dict)]
    prospects_in = _merge_observed_contacts(prospects_in, observed_contacts)
    if not prospects_in and (payload.lead or payload.account_id):
        prospects_in = [dict(payload.lead)] if payload.lead else [{"account_id": payload.account_id}]

    qualified_prospects: list[dict[str, Any]] = []
    scored_prospects: list[dict[str, Any]] = []
    for index, prospect in enumerate(prospects_in):
        lead = _normalize_observed_lead(dict(prospect))
        # Mission-scoped industry/location are evidence constraints for every
        # bound prospect, not just the first seed lead.
        for field in ("industry", "location", "intent", "automation_opportunity"):
            if field not in lead and payload.context.get(field):
                lead[field] = payload.context[field]
        if payload.lead and index == 0:
            # Merge seed lead fields without overwriting bound prospect identity.
            for key, value in payload.lead.items():
                lead.setdefault(key, value)
        result = _qualify_one(lead, context=payload.context, account_id=payload.account_id)
        company = str(lead.get("company") or lead.get("name") or f"prospect-{index + 1}")[:160]
        sources = _lead_source_references(lead)
        website = _first_lead_text(lead.get("website"), lead.get("url"))
        if not website and lead.get("domain"):
            website = f"https://{str(lead['domain']).strip()}"
        product_description = _first_lead_text(
            lead.get("product_description"),
            lead.get("description"),
            lead.get("products_services"),
        )[:1000]
        research_summary = _first_lead_text(
            lead.get("research_summary"),
            lead.get("signals"),
            lead.get("research_notes"),
        )[:1000]
        qualification_evidence = {
            "qualification_dimensions": result["qualification_dimensions"],
            "qualification_reasons": result["reasons"],
            "source_references": sources,
        }
        entry = {
            **{k: v for k, v in lead.items() if k not in {"score", "qualified", "reasons"}},
            "prospect_id": str(lead.get("prospect_id") or lead.get("id") or f"qualify:{index}:{company}")[:80],
            "company": company,
            "website": website[:500],
            "product_description": product_description,
            "research_summary": research_summary,
            "sources": sources,
            "qualification_evidence": qualification_evidence,
            "ajenda_relevance": _ajenda_relevance(lead=lead, context=payload.context),
            "score": result["score"],
            "score_10": result["score_10"],
            "qualification_dimensions": result["qualification_dimensions"],
            "qualification_threshold_10": result["qualification_threshold_10"],
            "qualified": result["qualified"],
            "reasons": result["reasons"],
            "disqualifiers": [] if result["qualified"] else result["reasons"],
            "recommended_next_action": (
                "Proceed to the next governed stage using this qualified prospect."
                if result["qualified"]
                else "Gather the missing qualification evidence before advancing this prospect."
            ),
        }
        scored_prospects.append(entry)
        if result["qualified"]:
            qualified_prospects.append(entry)

    # Qualification is a ranked stage. Preserve every score for evidence, but
    # pass only the requested strongest rows to downstream enrichment/drafting.
    qualified_prospects.sort(key=lambda item: (-int(item.get("score_10") or 0), str(item.get("prospect_id") or "")))
    requested_quantity = int(payload.context.get("requested_quantity") or len(qualified_prospects) or 0)
    if requested_quantity > 0:
        qualified_prospects = qualified_prospects[:requested_quantity]

    primary = (
        qualified_prospects[0]
        if qualified_prospects
        else scored_prospects[0]
        if scored_prospects
        else _qualify_one(payload.lead, context=payload.context, account_id=payload.account_id)
    )
    score = int(primary.get("score") or 0)
    qualified = bool(primary.get("qualified"))
    output = {
        "score": score,
        "score_10": primary.get("score_10", 0),
        "qualification_dimensions": primary.get("qualification_dimensions", {}),
        "qualification_threshold_10": primary.get("qualification_threshold_10", 7),
        "qualified": qualified,
        "reasons": primary.get("reasons") or ["insufficient local qualification signals"],
        "qualified_prospects": qualified_prospects,
        "prospect_count": len(qualified_prospects),
        "scored_prospects": scored_prospects,
    }
    summary = f"Qualified {len(qualified_prospects)} prospect(s); primary score={score}, qualified={qualified}."
    return ActionResult(
        action="sales.qualify",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.qualify",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )

def sales_score_lead(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    result = sales_qualify(invocation, context)
    output = {
        "lead_score": result.output["score"],
        "score_band": "high" if result.output["score"] >= 75 else "medium" if result.output["score"] >= 50 else "low",
        "reasons": result.output["reasons"],
    }
    summary = f"Lead score is {output['lead_score']} ({output['score_band']})."
    return ActionResult(
        action="sales.score_lead",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.score_lead",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.72,
            )
        ],
        summary=summary,
        confidence=0.72,
    )

def sales_recommend_next_action(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = SalesLeadInput.model_validate(invocation.input)
    qualify_result = sales_qualify(invocation, context)
    score = int(qualify_result.output["score"])
    recommendation = "draft_followup" if score >= 60 else "research_more"
    rationale = (
        "Qualification score is high enough for follow-up."
        if score >= 60
        else "More account/contact context is needed."
    )
    output = {"recommendation": recommendation, "rationale": rationale, "lead": payload.lead, "score": score}
    summary = f"Recommended next action: {recommendation}."
    return ActionResult(
        action="sales.recommend_next_action",
        provider="local_sales",
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="sales.recommend_next_action",
                provider="local_sales",
                summary=summary,
                payload=output,
                confidence=0.7,
            )
        ],
        summary=summary,
        confidence=0.7,
    )
