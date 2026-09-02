from __future__ import annotations

from backend.services.vertical_ops.research_intelligence import (
    ClaimAssessmentStatus,
    CompanyIdentityCandidate,
    ObservedResearchClaim,
    QualificationCriterion,
    QualificationStatus,
    ResearchSourceKind,
    ResearchSourceRecord,
    corroborate_claims,
    qualify_research_company,
    resolve_company_identity,
)


def _source(
    source_id: str,
    *,
    kind: ResearchSourceKind,
    independence_key: str,
    domain: str | None = None,
    name: str | None = None,
) -> ResearchSourceRecord:
    return ResearchSourceRecord(
        source_id=source_id,
        source_kind=kind,
        title=source_id,
        independence_key=independence_key,
        subject_domain=domain,
        subject_name=name,
    )


def test_article_search_hit_does_not_resolve_as_company() -> None:
    candidate = CompanyIdentityCandidate(
        candidate_id="web-1",
        claimed_name="Top AI Platforms",
        claimed_domain="example.com",
        source_ids=("article-1",),
    )
    source = _source(
        "article-1",
        kind=ResearchSourceKind.THIRD_PARTY_ARTICLE,
        independence_key="publisher:example",
        domain="example.com",
        name="Top AI Platforms",
    )
    assert resolve_company_identity(candidate=candidate, sources=(source,)) is None


def test_official_matching_identity_resolves_company() -> None:
    candidate = CompanyIdentityCandidate(
        candidate_id="candidate-1",
        claimed_name="Acme AI",
        claimed_domain="https://www.acme.example/product",
        source_ids=("official-1",),
    )
    source = _source(
        "official-1",
        kind=ResearchSourceKind.OFFICIAL_WEBSITE,
        independence_key="domain:acme.example",
        domain="acme.example",
        name="Acme AI",
    )
    resolved = resolve_company_identity(candidate=candidate, sources=(source,))
    assert resolved is not None
    assert resolved.canonical_key == "company:acme.example"


def test_two_independent_sources_support_claim_but_shared_lineage_does_not() -> None:
    sources = (
        _source("s1", kind=ResearchSourceKind.THIRD_PARTY_ARTICLE, independence_key="publisher:one"),
        _source("s2", kind=ResearchSourceKind.THIRD_PARTY_ARTICLE, independence_key="publisher:two"),
    )
    claims = tuple(
        ObservedResearchClaim(
            claim_id=f"c{index}",
            subject_key="company:acme.example",
            predicate="target_customer",
            value="enterprise",
            source_id=source.source_id,
            observed_at_iso="2026-09-02T00:00:00Z",
        )
        for index, source in enumerate(sources, start=1)
    )
    bundle = corroborate_claims(subject_key="company:acme.example", claims=claims, sources=sources)
    assert bundle.assessments[0].status == ClaimAssessmentStatus.SUPPORTED

    shared_sources = tuple(source.model_copy(update={"independence_key": "syndicated:one"}) for source in sources)
    shared = corroborate_claims(subject_key="company:acme.example", claims=claims, sources=shared_sources)
    assert shared.assessments[0].status == ClaimAssessmentStatus.GAP


def test_conflicting_values_remain_contradicted() -> None:
    sources = (
        _source("official", kind=ResearchSourceKind.OFFICIAL_WEBSITE, independence_key="domain:acme"),
        _source("article", kind=ResearchSourceKind.THIRD_PARTY_ARTICLE, independence_key="publisher:one"),
    )
    claims = (
        ObservedResearchClaim(
            claim_id="c1",
            subject_key="company:acme",
            predicate="pricing",
            value="contact_sales",
            source_id="official",
            observed_at_iso="2026-09-02T00:00:00Z",
        ),
        ObservedResearchClaim(
            claim_id="c2",
            subject_key="company:acme",
            predicate="pricing",
            value="free",
            source_id="article",
            observed_at_iso="2026-09-02T00:00:00Z",
        ),
    )
    bundle = corroborate_claims(subject_key="company:acme", claims=claims, sources=sources)
    assert bundle.assessments[0].status == ClaimAssessmentStatus.CONTRADICTED
    assert bundle.evidence_gaps == ("pricing",)


def test_required_evidence_gap_makes_qualification_indeterminate() -> None:
    bundle = corroborate_claims(
        subject_key="company:acme",
        claims=(),
        sources=(),
        required_predicates=("governance",),
    )
    assessment = qualify_research_company(
        bundle=bundle,
        criteria=(
            QualificationCriterion(
                criterion_id="enterprise-governance",
                predicate="governance",
                accepted_values=("yes",),
            ),
        ),
        rubric_version="owner-pending-1",
    )
    assert assessment.status == QualificationStatus.INDETERMINATE
    assert assessment.indeterminate_criteria == ("enterprise-governance",)
