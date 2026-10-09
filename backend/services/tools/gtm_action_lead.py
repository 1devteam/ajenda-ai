"""GTM lead-enrichment handler."""

from typing import Any

from backend.services.tools.external_sim_policy import allow_simulated_external
from backend.services.tools.gtm_action_common import _make_evidence
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    GtmLeadEnrichInput,
    SideEffectClass,
    ToolInvocation,
)


def lead_enrich_handler(inv: ToolInvocation, ctx: ActionRuntimeContext) -> ActionResult:
    merged_input = dict(inv.input)
    prospects_in = [p for p in (merged_input.get("prospects") or []) if isinstance(p, dict)]
    company_seed = str(merged_input.get("company", "") or "").strip()
    domain_seed = str(merged_input.get("domain", "") or "").strip() or None

    # Prefer bound prospects; do not overwrite prospect company with tenant profile.
    if not company_seed and prospects_in:
        company_seed = str(prospects_in[0].get("company") or "").strip()
        domain_seed = domain_seed or (str(prospects_in[0].get("domain") or "").strip() or None)
    if company_seed:
        merged_input["company"] = company_seed
    if domain_seed:
        merged_input["domain"] = domain_seed
    inp = GtmLeadEnrichInput.model_validate(merged_input)

    if bool(inp.context.get("binding_required")) and not prospects_in:
        raise ValueError(
            "gtm.lead_enrich requires bound upstream prospects when composition marks binding_required"
        )

    source_prospects = prospects_in or [
        {
            "prospect_id": f"enrich:{inp.company}",
            "company": inp.company,
            "domain": inp.domain or domain_seed,
        }
    ]
    enriched_prospects: list[dict[str, Any]] = []
    for index, prospect in enumerate(source_prospects):
        company = str(prospect.get("company") or inp.company or f"prospect-{index + 1}")[:160]
        domain = str(prospect.get("domain") or inp.domain or domain_seed or "").strip() or None
        existing = [item for item in (prospect.get("contacts") or []) if isinstance(item, dict)]
        real_existing = [
            item for item in existing if item.get("real") is True and item.get("simulated") is not True
        ]
        contacts: list[dict[str, Any]] = list(real_existing)
        enrichment_mode = "passthrough_observed"
        enrichment_real = bool(real_existing)
        if not contacts and domain and allow_simulated_external():
            contacts.append(
                {
                    "email": f"contact@{domain}",
                    "role": str(prospect.get("role") or "Owner"),
                    "real": False,
                    "simulated": True,
                    "source": "local_gtm_heuristic",
                }
            )
            enrichment_mode = "local_simulated"
            enrichment_real = False
        elif not contacts:
            enrichment_mode = "unresolved"
            enrichment_real = False
        enriched_prospects.append(
            {
                **{k: v for k, v in prospect.items() if k not in {"contacts"}},
                "prospect_id": str(prospect.get("prospect_id") or f"enrich:{index}:{company}")[:80],
                "company": company,
                "domain": domain,
                "contacts": contacts,
                "enrichment_real": enrichment_real,
                "enrichment_mode": enrichment_mode,
                "context": inp.context,
            }
        )

    primary = enriched_prospects[0]
    enriched = {
        "company": primary["company"],
        "domain": primary.get("domain"),
        "contacts": primary.get("contacts") or [],
        "context": inp.context,
        "enriched_prospects": enriched_prospects,
        "prospect_count": len(enriched_prospects),
        "real": any(item.get("enrichment_real") for item in enriched_prospects),
        "simulated": any(item.get("enrichment_mode") == "local_simulated" for item in enriched_prospects),
    }
    mode = str(primary.get("enrichment_mode") or "unresolved")
    summary = (
        f"Enriched {len(enriched_prospects)} prospect(s) ({mode})"
        if mode != "unresolved"
        else f"No real contacts available for {len(enriched_prospects)} prospect(s); none invented"
    )
    return ActionResult(
        action=inv.action,
        provider="local_gtm",
        side_effect_class=SideEffectClass.NONE,
        output=enriched,
        evidence=[_make_evidence(inv.action, "local_gtm", ctx, summary, enriched)],
        summary=summary,
    )
