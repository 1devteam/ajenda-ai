"""Project user-requested deliverable fields onto declared composition artifacts.

Projection is descriptive only. It does not select jobs, materialize artifacts,
grant authority, satisfy runtime inputs, or claim a field exists inside an
artifact unless the contract can prove that relationship.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.artifact_schemas import ARTIFACT_SCHEMAS_BY_KEY
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey, DeliverableRequest
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW, VerticalKnowHowContract

DeliverableBindingStatus = Literal["bound", "candidate", "unresolved"]
DeliverableBindingBasis = Literal[
    "typed_artifact_field",
    "whole_artifact_identity",
    "candidate_artifact",
    "no_declared_artifact",
]


class DeliverableFieldBinding(BaseModel):
    """Composition-time evidence for one requested deliverable field."""

    model_config = ConfigDict(extra="forbid")

    field_key: DeliverableFieldKey
    status: DeliverableBindingStatus
    basis: DeliverableBindingBasis
    artifact_keys: tuple[str, ...] = Field(default=(), max_length=20)
    producer_jobs: tuple[str, ...] = Field(default=(), max_length=20)
    grants_execution_authority: Literal[False] = False


class DeliverableProjection(BaseModel):
    """Non-authoritative projection from requested report fields to artifacts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["revops_report"] = "revops_report"
    bindings: tuple[DeliverableFieldBinding, ...] = Field(default=(), max_length=30)
    request_unresolved_items: tuple[str, ...] = Field(default=(), max_length=30)
    minimum_rows: int = Field(default=0, ge=0, le=1000)
    minimum_rows_by_artifact: dict[str, int] = Field(default_factory=dict)
    grants_execution_authority: Literal[False] = False

    @property
    def fully_bound(self) -> bool:
        return (
            bool(self.bindings)
            and not self.request_unresolved_items
            and all(binding.status == "bound" for binding in self.bindings)
        )

    @property
    def unresolved_fields(self) -> tuple[DeliverableFieldKey, ...]:
        return tuple(binding.field_key for binding in self.bindings if binding.status == "unresolved")

    @property
    def candidate_fields(self) -> tuple[DeliverableFieldKey, ...]:
        return tuple(binding.field_key for binding in self.bindings if binding.status == "candidate")


# Whole-artifact identity is intentionally narrow. Only the requested field
# "drafts" is currently equivalent to a declared artifact as a whole.
_WHOLE_ARTIFACT_BINDINGS: dict[DeliverableFieldKey, tuple[str, ...]] = {
    "drafts": ("introduction_drafts",),
    "source_url": ("web_page_observation", "public_identity_observation"),
    "final_url": ("web_page_observation", "public_identity_observation"),
    "title": ("web_page_observation", "public_identity_observation"),
    "extracted_observations": ("web_page_observation",),
    "observation_timestamp": ("web_page_observation",),
    "browser_trace": ("web_page_observation",),
    "blocked_requests": ("web_page_observation",),
    "observation_satisfied": ("web_page_observation",),
    "expected_company": ("public_identity_observation",),
    "expected_industry": ("public_identity_observation",),
    "expected_location": ("public_identity_observation",),
    "identity_status": ("public_identity_observation",),
    "identity_evidence_urls": ("public_identity_observation",),
    "identity_match_reasons": ("public_identity_observation",),
    "identity_match_evidence": ("public_identity_observation",),
    "identity_gaps": ("public_identity_observation",),
}

# Candidate artifacts indicate where a later typed artifact schema may prove a
# subfield. Candidate status is not deliverable satisfaction.
_CANDIDATE_ARTIFACTS: dict[DeliverableFieldKey, tuple[str, ...]] = {
    "company_name": (
        "verified_prospect_candidates",
        "prospect_candidates",
        "observed_contacts",
        "qualified_prospects",
        "enriched_prospects",
    ),
    "website": ("verified_prospect_candidates", "prospect_candidates", "researched_prospects", "enriched_prospects"),
    "product_description": ("researched_prospects",),
    "qualification_evidence": ("qualified_prospects",),
    "qualification_reasons": ("qualified_prospects",),
    "ajenda_relevance": ("researched_prospects", "recommendation"),
    "qualification_score": ("qualified_prospects",),
    "research_summary": ("verified_prospect_candidates", "prospect_candidates", "researched_prospects"),
    "sources": ("verified_prospect_candidates", "observed_contacts", "researched_prospects"),
}


def _declared_artifact_producers(contract: VerticalKnowHowContract) -> dict[str, tuple[str, ...]]:
    producers: dict[str, list[str]] = {}
    for stage in contract.stages:
        for job_key in stage.job_keys:
            job = BUSINESS_JOBS_BY_KEY[job_key]
            for artifact_key in job.produced_outputs:
                producers.setdefault(artifact_key, []).append(job_key)
    return {artifact_key: tuple(job_keys) for artifact_key, job_keys in producers.items()}


def _typed_binding(
    field_key: DeliverableFieldKey,
    *,
    producers: dict[str, tuple[str, ...]],
) -> DeliverableFieldBinding | None:
    matched_artifacts: list[str] = []
    matched_jobs: list[str] = []
    for artifact_key, schema in ARTIFACT_SCHEMAS_BY_KEY.items():
        if artifact_key not in producers or schema.producer_job not in producers[artifact_key]:
            continue
        if not any(field.deliverable_field == field_key for field in schema.fields):
            continue
        matched_artifacts.append(artifact_key)
        matched_jobs.append(schema.producer_job)
    if not matched_artifacts:
        return None
    # Prefer the terminal verified-company artifact when public research is in
    # the graph. Raw discovery remains an input artifact, not the deliverable
    # owner for overlapping fields.
    priority = {"verified_prospect_candidates": 0, "prospect_candidates": 1}
    ordered = sorted(
        zip(matched_artifacts, matched_jobs, strict=True),
        key=lambda item: priority.get(item[0], 2),
    )
    return DeliverableFieldBinding(
        field_key=field_key,
        status="bound",
        basis="typed_artifact_field",
        artifact_keys=tuple(item[0] for item in ordered),
        producer_jobs=tuple(dict.fromkeys(item[1] for item in ordered)),
    )


def _binding_for_field(
    field_key: DeliverableFieldKey,
    *,
    producers: dict[str, tuple[str, ...]],
) -> DeliverableFieldBinding:
    typed = _typed_binding(field_key, producers=producers)
    if typed is not None:
        return typed

    whole_artifacts = tuple(
        artifact_key for artifact_key in _WHOLE_ARTIFACT_BINDINGS.get(field_key, ()) if artifact_key in producers
    )
    if whole_artifacts:
        return DeliverableFieldBinding(
            field_key=field_key,
            status="bound",
            basis="whole_artifact_identity",
            artifact_keys=whole_artifacts,
            producer_jobs=tuple(dict.fromkeys(job for artifact in whole_artifacts for job in producers[artifact])),
        )

    candidate_artifacts = tuple(
        artifact_key for artifact_key in _CANDIDATE_ARTIFACTS.get(field_key, ()) if artifact_key in producers
    )
    if candidate_artifacts:
        return DeliverableFieldBinding(
            field_key=field_key,
            status="candidate",
            basis="candidate_artifact",
            artifact_keys=candidate_artifacts,
            producer_jobs=tuple(dict.fromkeys(job for artifact in candidate_artifacts for job in producers[artifact])),
        )

    return DeliverableFieldBinding(
        field_key=field_key,
        status="unresolved",
        basis="no_declared_artifact",
    )


def project_deliverable_request(
    request: DeliverableRequest,
    *,
    know_how: VerticalKnowHowContract = REVOPS_V1_KNOW_HOW,
    minimum_rows: int = 0,
    minimum_rows_by_artifact: dict[str, int] | None = None,
) -> DeliverableProjection:
    """Describe artifact support for a typed request without claiming execution readiness."""

    producers = _declared_artifact_producers(know_how)
    bindings = tuple(_binding_for_field(field.field_key, producers=producers) for field in request.fields)
    return DeliverableProjection(
        bindings=bindings,
        request_unresolved_items=request.unresolved_items,
        minimum_rows=minimum_rows,
        minimum_rows_by_artifact={key: value for key, value in (minimum_rows_by_artifact or {}).items() if value > 0},
    )
