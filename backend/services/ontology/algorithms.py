"""Bounded, deterministic intelligence algorithms.

Algorithms in this module evaluate structured observations only.  They return
typed read-model results with provenance; they never dispatch actions, resolve
credentials, approve work, or grant runtime authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlgorithmDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_contract: str = Field(min_length=1)
    output_contract: str = Field(min_length=1)
    deterministic: bool = True
    applicable_domains: tuple[str, ...] = ()
    applicable_verticals: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    confidence_semantics: str = Field(min_length=1)
    cost_class: Literal["zero", "low", "bounded"] = "zero"
    provenance: dict[str, Any] = Field(default_factory=dict)
    grants_execution_authority: Literal[False] = False


class AlgorithmResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["evaluated", "insufficient_evidence", "conflict"]
    output: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = ()
    input_sha256: str = Field(min_length=64, max_length=64)
    provenance: dict[str, Any] = Field(default_factory=dict)
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_integrity(self) -> AlgorithmResult:
        definition = algorithm_definition(self.algorithm_id, self.version)
        if self.provenance.get("algorithm_id") != definition.algorithm_id:
            raise ValueError("algorithm result provenance does not match algorithm identity")
        if self.provenance.get("algorithm_version") != definition.version:
            raise ValueError("algorithm result provenance does not match algorithm version")
        if self.authority_class != "read_model" or self.grants_execution_authority is not False:
            raise ValueError("algorithm results cannot grant runtime authority")
        if len(self.input_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.input_sha256):
            raise ValueError("algorithm result input hash must be a lowercase SHA-256 digest")
        return self


ALGORITHM_REGISTRY: tuple[AlgorithmDefinition, ...] = (
    AlgorithmDefinition(
        algorithm_id="geo.service_area_match.v1",
        version="1",
        display_name="Service-area match",
        description="Compares an observed target location to an explicit service-area set.",
        input_contract="target_location plus service_areas",
        output_contract="service_area_match_result",
        applicable_domains=("local_service_business", "field_service"),
        applicable_verticals=("hvac", "roofing", "plumbing", "electrical"),
        required_evidence=("target location", "service area observation"),
        confidence_semantics="Confidence reflects explicit normalized token agreement.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    AlgorithmDefinition(
        algorithm_id="identity.business_verification.v1",
        version="1",
        display_name="Business identity verification",
        description="Checks whether observed identity fields agree across structured sources.",
        input_contract="identity observations",
        output_contract="identity_verification_result",
        applicable_domains=("gtm", "local_service_business"),
        required_evidence=("identity observations",),
        confidence_semantics="Confidence is the proportion of non-conflicting identity fields.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    AlgorithmDefinition(
        algorithm_id="gtm.lead_fit_score.v1",
        version="1",
        display_name="GTM lead-fit score",
        description="Scores explicit fit signals without inventing missing business facts.",
        input_contract="structured fit signals",
        output_contract="lead_fit_score_result",
        applicable_domains=("gtm", "b2b_sales"),
        required_evidence=("fit signals",),
        confidence_semantics="Confidence is bounded by the completeness of supplied signals.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    AlgorithmDefinition(
        algorithm_id="gtm.evidence_completeness.v1",
        version="1",
        display_name="Evidence completeness",
        description="Measures whether a composed mission has named outcomes, jobs, steps, and evidence.",
        input_contract="composition read model",
        output_contract="evidence_completeness_result",
        applicable_domains=("gtm", "mission_composition"),
        required_evidence=("MissionIntent", "BusinessJob", "PlannedStepPreview"),
        confidence_semantics="Confidence equals the reproducible completeness score.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    AlgorithmDefinition(
        algorithm_id="gtm.source_confidence.v1",
        version="1",
        display_name="GTM source confidence",
        description="Aggregates explicit interpretation evidence confidence and visible gaps.",
        input_contract="interpretation evidence plus layer gaps",
        output_contract="source_confidence_result",
        applicable_domains=("gtm", "mission_composition"),
        required_evidence=("interpretation evidence",),
        confidence_semantics="Confidence is the bounded mean of supplied evidence confidence.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
    AlgorithmDefinition(
        algorithm_id="gtm.runtime_artifact_completeness.v1",
        version="1",
        display_name="Runtime artifact completeness",
        description="Compares persisted runtime outputs with the declared acceptance contract.",
        input_contract="terminal task outputs plus acceptance contract",
        output_contract="runtime_artifact_completeness_result",
        applicable_domains=("gtm", "mission_runtime"),
        required_evidence=("terminal task outputs", "acceptance contract"),
        confidence_semantics="Confidence is one only when the declared runtime acceptance contract is met.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-29"},
    ),
    AlgorithmDefinition(
        algorithm_id="gtm.duplicate_identity_resolution.v1",
        version="1",
        display_name="Duplicate identity resolution",
        description="Groups structured records by normalized email, domain, or name.",
        input_contract="records with optional email, domain, and name",
        output_contract="duplicate_identity_result",
        applicable_domains=("gtm", "crm"),
        required_evidence=("structured records",),
        confidence_semantics="Confidence is high only when a stable identifier agrees.",
        provenance={"source_type": "algorithm_registry", "source_name": "Ajenda", "version_date": "2026-09-27"},
    ),
)

_ALGORITHMS_BY_ID = {(item.algorithm_id, item.version): item for item in ALGORITHM_REGISTRY}


def validate_algorithm_registry() -> None:
    ids = [item.algorithm_id for item in ALGORITHM_REGISTRY]
    if len(ids) != len(set(ids)):
        raise ValueError("algorithm IDs must be unique")
    if any(item.grants_execution_authority for item in ALGORITHM_REGISTRY):
        raise ValueError("algorithms cannot grant execution authority")


def algorithm_definition(algorithm_id: str, version: str = "1") -> AlgorithmDefinition:
    try:
        return _ALGORITHMS_BY_ID[(algorithm_id, version)]
    except KeyError as exc:
        raise ValueError(f"unknown algorithm: {algorithm_id}@{version}") from exc


def _input_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _result(
    algorithm_id: str,
    payload: dict[str, Any],
    *,
    status: Literal["evaluated", "insufficient_evidence", "conflict"],
    output: dict[str, Any],
    confidence: float,
    evidence_refs: tuple[str, ...] = (),
) -> AlgorithmResult:
    definition = algorithm_definition(algorithm_id)
    return AlgorithmResult(
        algorithm_id=algorithm_id,
        version=definition.version,
        status=status,
        output=output,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        evidence_refs=evidence_refs,
        input_sha256=_input_hash(payload),
        provenance={**definition.provenance, "algorithm_id": algorithm_id, "algorithm_version": definition.version},
    )


def evaluate_composition_algorithms(
    *,
    requested_outcomes: list[str],
    named_jobs: list[str],
    planned_steps: list[str],
    interpretation_evidence: list[dict[str, Any]],
    blocking_gap_count: int,
) -> tuple[AlgorithmResult, ...]:
    """Evaluate reproducible intelligence signals for one composition."""

    completeness_input = {
        "requested_outcomes": requested_outcomes,
        "named_jobs": named_jobs,
        "planned_steps": planned_steps,
        "blocking_gap_count": blocking_gap_count,
    }
    expected = len(requested_outcomes) + len(named_jobs) + len(planned_steps)
    complete = expected > 0 and len(named_jobs) >= len(requested_outcomes) and len(planned_steps) >= len(named_jobs)
    gap_penalty = min(1.0, blocking_gap_count / max(1, expected))
    completeness_score = 0.0 if expected == 0 else max(0.0, (1.0 if complete else 0.5) - gap_penalty)
    completeness = _result(
        "gtm.evidence_completeness.v1",
        completeness_input,
        status="evaluated" if complete and blocking_gap_count == 0 else "insufficient_evidence",
        output={
            "evaluation_phase": "composition",
            "requested_outcome_count": len(requested_outcomes),
            "named_job_count": len(named_jobs),
            "planned_step_count": len(planned_steps),
            "blocking_gap_count": blocking_gap_count,
            "completeness_score": round(completeness_score, 4),
        },
        confidence=completeness_score,
        evidence_refs=("intent.requested_outcomes", "composition.jobs", "composition.planned_steps"),
    )
    confidence_values = [
        float(item["confidence"])
        for item in interpretation_evidence
        if isinstance(item, dict) and isinstance(item.get("confidence"), (int, float))
    ]
    source_input = {"interpretation_evidence": interpretation_evidence, "blocking_gap_count": blocking_gap_count}
    source_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    if blocking_gap_count:
        source_confidence *= max(0.0, 1.0 - min(1.0, blocking_gap_count / 10))
    source = _result(
        "gtm.source_confidence.v1",
        source_input,
        status="evaluated" if confidence_values and blocking_gap_count == 0 else "insufficient_evidence",
        output={
            "evaluation_phase": "composition",
            "evidence_count": len(confidence_values),
            "blocking_gap_count": blocking_gap_count,
            "source_confidence": round(source_confidence, 4),
        },
        confidence=source_confidence,
        evidence_refs=tuple(
            str(item.get("field_path"))
            for item in interpretation_evidence
            if isinstance(item, dict) and item.get("field_path")
        ),
    )
    return completeness, source


def evaluate_runtime_artifact_completeness(
    *,
    task_count: int,
    failed_task_count: int,
    acceptance_met: bool,
    acceptance_reasons: list[str],
    materialized_artifact_keys: list[str],
) -> AlgorithmResult:
    """Evaluate the persisted runtime result, separately from composition quality.

    Composition algorithms describe whether Ajenda could plan a mission. This
    algorithm describes what the worker actually delivered. Keeping the phases
    separate prevents a complete plan from being reported as a complete result
    after execution produced partial or rejected artifacts.
    """

    payload = {
        "task_count": task_count,
        "failed_task_count": failed_task_count,
        "acceptance_met": acceptance_met,
        "acceptance_reasons": list(acceptance_reasons),
        "materialized_artifact_keys": sorted(set(materialized_artifact_keys)),
    }
    score = 1.0 if acceptance_met and failed_task_count == 0 and task_count > 0 else 0.0
    status: Literal["evaluated", "insufficient_evidence", "conflict"] = (
        "evaluated" if task_count > 0 else "insufficient_evidence"
    )
    return _result(
        "gtm.runtime_artifact_completeness.v1",
        payload,
        status=status,
        output={
            "evaluation_phase": "runtime",
            "task_count": task_count,
            "failed_task_count": failed_task_count,
            "acceptance_met": acceptance_met,
            "acceptance_reasons": list(acceptance_reasons),
            "materialized_artifact_keys": sorted(set(materialized_artifact_keys)),
            "completeness_score": score,
        },
        confidence=score,
        evidence_refs=("runtime.tasks", "runtime.acceptance", "runtime.materialized_artifacts"),
    )


def validate_composition_algorithm_results(
    *,
    results: tuple[AlgorithmResult, ...],
    requested_outcomes: list[str],
    named_jobs: list[str],
    planned_steps: list[str],
    interpretation_evidence: list[dict[str, Any]],
    blocking_gap_count: int,
) -> None:
    """Fail closed when persisted composition signals are stale or incomplete.

    Empty results remain valid for historical records created before algorithm
    signals existed. New records must exactly match the current deterministic
    evaluation for their composition inputs.
    """

    if not results:
        return
    expected = evaluate_composition_algorithms(
        requested_outcomes=requested_outcomes,
        named_jobs=named_jobs,
        planned_steps=planned_steps,
        interpretation_evidence=interpretation_evidence,
        blocking_gap_count=blocking_gap_count,
    )
    if tuple(item.model_dump(mode="json") for item in results) != tuple(
        item.model_dump(mode="json") for item in expected
    ):
        raise ValueError("algorithm results are stale or inconsistent with composition inputs")


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def evaluate_duplicate_identity_resolution(records: list[dict[str, Any]]) -> AlgorithmResult:
    """Group records by stable identity fields without mutating or dispatching."""

    groups: dict[str, list[str]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        identity = (
            _normalized(record.get("email")) or _normalized(record.get("domain")) or _normalized(record.get("name"))
        )
        if identity:
            groups.setdefault(identity, []).append(str(record.get("id") or index))
    duplicates = [sorted(ids) for ids in groups.values() if len(ids) > 1]
    payload = {"records": records}
    return _result(
        "gtm.duplicate_identity_resolution.v1",
        payload,
        status="evaluated" if records else "insufficient_evidence",
        output={"duplicate_groups": duplicates, "duplicate_group_count": len(duplicates)},
        confidence=1.0 if records else 0.0,
        evidence_refs=("records",) if records else (),
    )


def evaluate_service_area_match(*, target_location: str | None, service_areas: list[str]) -> AlgorithmResult:
    """Match explicit location tokens; missing inputs remain unproven."""

    payload = {"target_location": target_location, "service_areas": service_areas}
    target = _normalized(target_location)
    areas = {_normalized(item) for item in service_areas if _normalized(item)}
    if not target or not areas:
        return _result(
            "geo.service_area_match.v1",
            payload,
            status="insufficient_evidence",
            output={"matched": None, "reason": "target_location_and_service_areas_required"},
            confidence=0.0,
        )
    matched = target in areas or any(area in target or target in area for area in areas)
    return _result(
        "geo.service_area_match.v1",
        payload,
        status="evaluated",
        output={"matched": matched, "target_location": target, "service_areas": sorted(areas)},
        confidence=1.0,
        evidence_refs=("target_location", "service_areas"),
    )


validate_algorithm_registry()
