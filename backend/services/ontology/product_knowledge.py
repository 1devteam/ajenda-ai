"""Canonical, declarative product knowledge shared by Ajenda's existing shelves.

This module is a read model only.  Product capabilities describe what the
composition and retrieval layers may explain; they never register handlers,
resolve credentials, dispatch work, or grant runtime authority.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductKnowledge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    canonical_outcomes: tuple[str, ...] = ()
    job_keys: tuple[str, ...] = ()
    applicable_verticals: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    evidence_expectations: tuple[str, ...] = ()
    algorithm_ids: tuple[str, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)
    grants_execution_authority: bool = False


AJENDA_PRODUCT_KNOWLEDGE: tuple[ProductKnowledge, ...] = (
    ProductKnowledge(
        capability_id="ajenda.mission_composition",
        version="1",
        display_name="Governed mission composition",
        summary="Interprets an instruction into validated business jobs and a reviewable plan.",
        aliases=("mission composition", "mission planning", "business jobs"),
        canonical_outcomes=("research_prospects", "qualify_prospects", "read_business_profile"),
        job_keys=("intelligence.retrieve_business_profile",),
        limitations=("Composition does not grant runtime authority.",),
        evidence_expectations=("MissionCompositionRecord", "composition provenance"),
        provenance={"source_type": "product_catalog", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    ProductKnowledge(
        capability_id="ajenda.governed_runtime",
        version="1",
        display_name="Governed mission runtime",
        summary="Runs admitted work through the queue, lease, action, evidence, and artifact path.",
        aliases=("mission execution", "worker runtime", "governed execution"),
        limitations=("Execution remains subject to tenant policy, capability, approval, and lease checks.",),
        evidence_expectations=("ActionResult", "EvidenceItem", "runtime artifact"),
        provenance={"source_type": "product_catalog", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    ProductKnowledge(
        capability_id="ajenda.crm_operations",
        version="1",
        display_name="CRM operations",
        summary="Reads, reconciles, verifies, and prepares governed CRM changes through registered actions.",
        aliases=("crm", "crm research", "crm reconciliation", "pipeline operations"),
        canonical_outcomes=("read_crm", "prepare_reconciliation", "update_crm"),
        applicable_verticals=("gtm", "sales", "revenue_operations"),
        limitations=("Provider credentials and external writes are separately governed.",),
        evidence_expectations=("CRM provider evidence", "readback or reconciliation evidence"),
        provenance={"source_type": "product_catalog", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    ProductKnowledge(
        capability_id="ajenda.gtm_research",
        version="1",
        display_name="Evidence-backed GTM research",
        summary="Discovers, qualifies, enriches, and drafts outreach from bounded evidence.",
        aliases=("gtm", "prospect research", "lead qualification", "outreach drafting"),
        canonical_outcomes=("research_prospects", "qualify_prospects", "enrich_contacts", "prepare_outreach"),
        applicable_verticals=("gtm", "revenue_operations", "b2b_sales"),
        limitations=("Drafting is distinct from sending; research does not imply contact authority.",),
        evidence_expectations=("source observations", "qualification evidence", "draft artifact"),
        algorithm_ids=("gtm.lead_fit_score.v1", "gtm.evidence_completeness.v1", "gtm.source_confidence.v1"),
        provenance={"source_type": "product_catalog", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    ProductKnowledge(
        capability_id="ajenda.browser_research",
        version="1",
        display_name="Bounded browser research",
        summary="Collects typed read-only web observations through the governed browser session.",
        aliases=("browser research", "web research", "website observation"),
        canonical_outcomes=("observe_web_page", "verify_public_identity"),
        applicable_verticals=("all",),
        limitations=("Explicit target URLs and browser allow-list policy remain required.",),
        evidence_expectations=("typed web observation", "browser step trace"),
        algorithm_ids=("identity.business_verification.v1", "geo.service_area_match.v1"),
        provenance={"source_type": "product_catalog", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
)


def validate_product_catalog(catalog: tuple[ProductKnowledge, ...] = AJENDA_PRODUCT_KNOWLEDGE) -> None:
    """Fail closed on duplicate or authority-bearing product declarations."""

    ids = [item.capability_id for item in catalog]
    if len(ids) != len(set(ids)):
        raise ValueError("product knowledge capability IDs must be unique")
    if any(item.grants_execution_authority for item in catalog):
        raise ValueError("product knowledge cannot grant execution authority")


def product_catalog_hits(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return deterministic, inspectable catalog hits for explicit product queries."""

    normalized = " ".join(query.lower().split())
    if not any(token in normalized for token in ("ajenda", "product", "capabilit", "what can", "feature")):
        return []
    hits: list[dict[str, Any]] = []
    for item in AJENDA_PRODUCT_KNOWLEDGE:
        terms = (item.display_name.lower(), item.capability_id.lower(), *item.aliases)
        if any(term in normalized for term in terms) or "ajenda" in normalized:
            hits.append(
                {
                    "id": f"product-knowledge:{item.capability_id}:{item.version}",
                    "content": item.model_dump(mode="json"),
                    "source": "ajenda_product_knowledge",
                    "search_mode": "canonical_product_catalog",
                    "score": 0.98,
                }
            )
        if len(hits) >= limit:
            break
    return hits


validate_product_catalog()
