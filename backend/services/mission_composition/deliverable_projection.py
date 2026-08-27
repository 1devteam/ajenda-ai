"""Project user-requested deliverable fields onto declared composition artifacts.

Projection is descriptive only. It does not select jobs, materialize artifacts,
grant authority, satisfy runtime inputs, or claim a field exists inside an
artifact unless the contract can prove that relationship.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey, DeliverableRequest
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY
from backend.services.mission_composition.vertical_know_how import REVOPS_V1_KNOW_HOW, VerticalKnowHowContract

DeliverableBindingStatus = Literal["bound", "candidate", "unresolved"]
DeliverableBindingBasis = Literal["whole_artifact_identity", "candidate_artifact", "no_declared_artifact"]


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
}

# Candidate artifacts indicate where a later typed artifact schema may prove a
# subfield. Candidate status is not deliverable satisfaction.
_CANDIDATE_ARTIFACTS: dict[DeliverableFieldKey, tuple[str, ...]] = {
    "company_name": ("prospect_candidates", "observed_contacts", "qualified_prospects", "enriched_prospects"),
    "website": ("prospect_candidates", "researched_prospects", "enriched_prospects"),
    "product_description": ("researched_prospects",),
    "qualification_evidence": ("qualified_prospects",),
    "qualification_reasons": ("qualified_prospects",),
    "ajenda_relevance": ("researched_prospects", "recommendation"),
    "qualification_score": ("qualified_prospects",),
    "research_summary": ("researched_prospects",),
    "sources": ("observed_contacts", "researched_prospects"),
}


def _declared_artifact_producers(contract: VerticalKnowHowContract) -> dict[str, tuple[str, ...]]:
    producers: dict[str, list[str]] = {}
    for stage in contract.stages:
        for job_key in stage.job_keys:
            job = BUSINESS_JOBS_BY_KEY[job_key]
            for artifact_key in job.produced_outputs:
                producers.setdefault(artifact_key, []).append(job_key)
    return {artifact_key: tuple(job_keys) for artifact_key, job_keys in producers.items()}


def _binding_for_field(
    field_key: DeliverableFieldKey,
    *,
    producers: dict[str, tuple[str, ...]],
) -> DeliverableFieldBinding:
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
) -> DeliverableProjection:
    """Describe artifact support for a typed request without claiming execution readiness."""

    producers = _declared_artifact_producers(know_how)
    bindings = tuple(_binding_for_field(field.field_key, producers=producers) for field in request.fields)
    return DeliverableProjection(
        bindings=bindings,
        request_unresolved_items=request.unresolved_items,
    )
