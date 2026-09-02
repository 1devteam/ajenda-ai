"""Provider-neutral research identity, corroboration, and qualification logic.

The module consumes typed observations. It performs no retrieval, persistence,
credential access, action registration, or runtime dispatch.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResearchSourceKind(StrEnum):
    OFFICIAL_WEBSITE = "official_website"
    PROVIDER_DOCUMENT = "provider_document"
    THIRD_PARTY_ARTICLE = "third_party_article"
    PUBLIC_SEARCH_RESULT = "public_search_result"
    CRM_RECORD = "crm_record"


class ClaimAssessmentStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    GAP = "gap"
    STALE = "stale"


class QualificationStatus(StrEnum):
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    INDETERMINATE = "indeterminate"


class ResearchSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    source_id: str = Field(min_length=1, max_length=240)
    source_kind: ResearchSourceKind
    url: str | None = Field(default=None, max_length=2048)
    title: str = Field(min_length=1, max_length=500)
    independence_key: str = Field(min_length=1, max_length=240)
    subject_name: str | None = Field(default=None, max_length=240)
    subject_domain: str | None = Field(default=None, max_length=255)

    @field_validator("subject_domain")
    @classmethod
    def normalize_subject_domain(cls, value: str | None) -> str | None:
        return normalize_domain(value) if value else None


class CompanyIdentityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1, max_length=240)
    claimed_name: str = Field(min_length=1, max_length=240)
    claimed_domain: str | None = Field(default=None, max_length=255)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=100)

    @field_validator("claimed_domain")
    @classmethod
    def normalize_claimed_domain(cls, value: str | None) -> str | None:
        return normalize_domain(value) if value else None


class ResolvedResearchCompany(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_key: str = Field(min_length=1, max_length=320)
    name: str = Field(min_length=1, max_length=240)
    primary_domain: str = Field(min_length=1, max_length=255)
    identity_source_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    candidate_id: str = Field(min_length=1, max_length=240)


class ObservedResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=240)
    subject_key: str = Field(min_length=1, max_length=320)
    predicate: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=240)
    observed_at_iso: str = Field(min_length=1, max_length=80)


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_key: str
    predicate: str
    value: str | None = None
    status: ClaimAssessmentStatus
    supporting_claim_ids: tuple[str, ...] = ()
    contradicting_claim_ids: tuple[str, ...] = ()
    independent_source_count: int = Field(default=0, ge=0)
    reason: str = Field(min_length=1, max_length=500)


class CorroborationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    subject_key: str = Field(min_length=1, max_length=320)
    assessments: tuple[ClaimAssessment, ...]
    evidence_gaps: tuple[str, ...]


class QualificationCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(min_length=1, max_length=120)
    predicate: str = Field(min_length=1, max_length=160)
    accepted_values: tuple[str, ...] = Field(min_length=1, max_length=100)
    required: bool = True


class ResearchQualificationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_key: str
    rubric_version: str = Field(min_length=1, max_length=80)
    status: QualificationStatus
    satisfied_criteria: tuple[str, ...]
    failed_criteria: tuple[str, ...]
    indeterminate_criteria: tuple[str, ...]
    evidence_claim_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> ResearchQualificationAssessment:
        groups = (set(self.satisfied_criteria), set(self.failed_criteria), set(self.indeterminate_criteria))
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError("qualification criterion result groups must not overlap")
        return self


def normalize_domain(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        raise ValueError("domain must be non-empty")
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        raise ValueError("domain must contain a public-style hostname")
    return host


def resolve_company_identity(
    *,
    candidate: CompanyIdentityCandidate,
    sources: tuple[ResearchSourceRecord, ...],
) -> ResolvedResearchCompany | None:
    """Resolve only from identity-bearing source types with matching subject data."""

    if candidate.claimed_domain is None:
        return None
    by_id = {source.source_id: source for source in sources}
    evidence: list[str] = []
    for source_id in candidate.source_ids:
        source = by_id.get(source_id)
        if source is None or source.source_kind not in {
            ResearchSourceKind.OFFICIAL_WEBSITE,
            ResearchSourceKind.CRM_RECORD,
        }:
            continue
        if source.subject_domain != candidate.claimed_domain:
            continue
        if source.subject_name and source.subject_name.casefold() != candidate.claimed_name.casefold():
            continue
        evidence.append(source.source_id)
    if not evidence:
        return None
    return ResolvedResearchCompany(
        canonical_key=f"company:{candidate.claimed_domain}",
        name=candidate.claimed_name.strip(),
        primary_domain=candidate.claimed_domain,
        identity_source_ids=tuple(sorted(set(evidence))),
        candidate_id=candidate.candidate_id,
    )


def corroborate_claims(
    *,
    subject_key: str,
    claims: tuple[ObservedResearchClaim, ...],
    sources: tuple[ResearchSourceRecord, ...],
    required_predicates: tuple[str, ...] = (),
) -> CorroborationBundle:
    source_by_id = {source.source_id: source for source in sources}
    grouped: dict[str, list[ObservedResearchClaim]] = defaultdict(list)
    for claim in claims:
        if claim.subject_key == subject_key and claim.source_id in source_by_id:
            grouped[claim.predicate].append(claim)

    assessments: list[ClaimAssessment] = []
    for predicate in sorted(set(grouped) | set(required_predicates)):
        predicate_claims = grouped.get(predicate, [])
        if not predicate_claims:
            assessments.append(
                ClaimAssessment(
                    subject_key=subject_key,
                    predicate=predicate,
                    status=ClaimAssessmentStatus.GAP,
                    reason="No observed claim supplies the required predicate.",
                )
            )
            continue
        by_value: dict[str, list[ObservedResearchClaim]] = defaultdict(list)
        for claim in predicate_claims:
            by_value[claim.value].append(claim)
        ranked = sorted(
            by_value.items(),
            key=lambda item: len({source_by_id[claim.source_id].independence_key for claim in item[1]}),
            reverse=True,
        )
        value, supporting = ranked[0]
        contradicting = [claim for other_value, items in ranked[1:] if other_value != value for claim in items]
        independence_keys = {source_by_id[claim.source_id].independence_key for claim in supporting}
        has_authoritative = any(
            source_by_id[claim.source_id].source_kind
            in {
                ResearchSourceKind.OFFICIAL_WEBSITE,
                ResearchSourceKind.CRM_RECORD,
                ResearchSourceKind.PROVIDER_DOCUMENT,
            }
            for claim in supporting
        )
        if contradicting:
            status = ClaimAssessmentStatus.CONTRADICTED
            reason = "Observed sources assert conflicting values."
        elif has_authoritative or len(independence_keys) >= 2:
            status = ClaimAssessmentStatus.SUPPORTED
            reason = "Supported by an authoritative source or two independent sources."
        else:
            status = ClaimAssessmentStatus.GAP
            reason = "Only one non-authoritative source supports the value."
        assessments.append(
            ClaimAssessment(
                subject_key=subject_key,
                predicate=predicate,
                value=value,
                status=status,
                supporting_claim_ids=tuple(sorted(claim.claim_id for claim in supporting)),
                contradicting_claim_ids=tuple(sorted(claim.claim_id for claim in contradicting)),
                independent_source_count=len(independence_keys),
                reason=reason,
            )
        )
    gaps = tuple(
        assessment.predicate for assessment in assessments if assessment.status != ClaimAssessmentStatus.SUPPORTED
    )
    return CorroborationBundle(
        subject_key=subject_key,
        assessments=tuple(assessments),
        evidence_gaps=gaps,
    )


def qualify_research_company(
    *,
    bundle: CorroborationBundle,
    criteria: tuple[QualificationCriterion, ...],
    rubric_version: str,
) -> ResearchQualificationAssessment:
    by_predicate = {assessment.predicate: assessment for assessment in bundle.assessments}
    satisfied: list[str] = []
    failed: list[str] = []
    indeterminate: list[str] = []
    evidence_ids: set[str] = set()
    for criterion in criteria:
        assessment = by_predicate.get(criterion.predicate)
        if assessment is None or assessment.status != ClaimAssessmentStatus.SUPPORTED:
            if criterion.required:
                indeterminate.append(criterion.criterion_id)
            continue
        evidence_ids.update(assessment.supporting_claim_ids)
        if assessment.value in criterion.accepted_values:
            satisfied.append(criterion.criterion_id)
        else:
            failed.append(criterion.criterion_id)
    if indeterminate:
        status = QualificationStatus.INDETERMINATE
    elif failed:
        status = QualificationStatus.DISQUALIFIED
    else:
        status = QualificationStatus.QUALIFIED
    return ResearchQualificationAssessment(
        subject_key=bundle.subject_key,
        rubric_version=rubric_version,
        status=status,
        satisfied_criteria=tuple(satisfied),
        failed_criteria=tuple(failed),
        indeterminate_criteria=tuple(indeterminate),
        evidence_claim_ids=tuple(sorted(evidence_ids)),
    )
