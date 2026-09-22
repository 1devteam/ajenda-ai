"""Assemble a read-only RevOps mission deliverable from runtime-owned artifacts.

The assembler is descriptive. It validates tenant/mission ownership, reads only
completed task artifacts, recomputes deliverable completion, and projects current
approval/effect evidence. It never mutates missions or tasks, grants authority,
queues work, or performs an external effect.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.artifact_schemas import ARTIFACT_SCHEMAS_BY_KEY
from backend.services.mission_composition.deliverable_completion import (
    DeliverableCompletion,
    MaterializedArtifact,
    evaluate_deliverable_completion,
    validate_materialized_artifact,
)
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    load_deliverable_runtime_state,
)
from backend.services.tools.schemas import SideEffectAuthorization, SideEffectAuthorizationV2, SideEffectClass

_DRAFT_REVIEW_STATUSES = frozenset({"pending", "approved", "rejected", "sent"})
_TERMINAL_TASK_STATES = frozenset(
    {
        ExecutionTaskState.COMPLETED.value,
        ExecutionTaskState.FAILED.value,
        ExecutionTaskState.CANCELLED.value,
        ExecutionTaskState.DEAD_LETTERED.value,
        ExecutionTaskState.BLOCKED.value,
    }
)


class RevOpsObservedContactRead(BaseModel):
    """One contact value observed in a materialized research artifact."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = None
    value: str | None = None
    source_url: str | None = None
    real: bool = False


class RevOpsDraftRead(BaseModel):
    """One materialized outreach draft and its current review state."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str | None = None
    prospect_id: str | None = None
    company_name: str | None = None
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None
    review_status: Literal["pending", "approved", "rejected", "sent", "unresolved"] = "unresolved"
    recipient_bound: bool = False


class RevOpsProspectRead(BaseModel):
    """Artifact-backed final report row for one prospect identity."""

    model_config = ConfigDict(extra="forbid")

    prospect_id: str | None = None
    company_name: str | None = None
    website: str | None = None
    product_description: str | None = None
    research_summary: str | None = None
    sources: tuple[str, ...] = ()
    observed_contacts: tuple[RevOpsObservedContactRead, ...] = ()
    qualification_evidence: dict[str, Any] | None = None
    ajenda_relevance: str | None = None
    qualification_score: int | None = None
    qualification_reasons: tuple[str, ...] = ()
    drafts: tuple[RevOpsDraftRead, ...] = ()


class RevOpsDraftApprovalRead(BaseModel):
    """Current review authority state for one persisted draft artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str | None = None
    status: Literal["pending", "approved", "rejected", "sent", "unresolved"]


class RevOpsTaskApprovalRead(BaseModel):
    """Descriptive state of one task-bound side-effect approval."""

    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    action: str | None = None
    task_status: str
    status: Literal["pending", "approved", "consumed", "expired", "revoked", "invalid"]
    grant_id: uuid.UUID | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None


class RevOpsOutcomeReviewRead(BaseModel):
    """Compact outcome-review state included in the final report."""

    model_config = ConfigDict(extra="forbid")

    review_id: uuid.UUID
    review_status: str
    review_decision: str
    human_approval_required: bool
    human_approval_status: str | None = None


class RevOpsApprovalStateRead(BaseModel):
    """All observable review gates without granting or consuming authority."""

    model_config = ConfigDict(extra="forbid")

    draft_approvals: tuple[RevOpsDraftApprovalRead, ...] = ()
    task_approvals: tuple[RevOpsTaskApprovalRead, ...] = ()
    outcome_reviews: tuple[RevOpsOutcomeReviewRead, ...] = ()
    all_required_approved: bool = True
    grants_execution_authority: Literal[False] = False


class RevOpsEffectRead(BaseModel):
    """Persisted result of one side-effect-classified task."""

    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    action: str | None = None
    side_effect_class: SideEffectClass
    task_status: str
    status: str
    real: bool
    provider: str | None = None
    receipt_status: Literal["recorded", "missing", "simulated", "not_applicable"]
    receipt: dict[str, Any] | None = None
    evidence_ids: tuple[uuid.UUID, ...] = ()


class RevOpsEvidenceReferenceRead(BaseModel):
    """Compact durable evidence reference for the assembled report."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: uuid.UUID
    execution_task_id: uuid.UUID | None = None
    evidence_type: str
    evidence_source: str
    summary: str
    confidence: float | None = None
    collection_status: str


class RevOpsTaskStateRead(BaseModel):
    """Task state kept explicitly separate from deliverable completion."""

    model_config = ConfigDict(extra="forbid")

    task_count: int = 0
    statuses: dict[str, int] = Field(default_factory=dict)
    all_terminal: bool = False
    all_succeeded: bool = False


class RevOpsCompletionRead(BaseModel):
    """Recomputed artifact-backed deliverable completion."""

    model_config = ConfigDict(extra="forbid")

    requested_fields: tuple[DeliverableFieldKey, ...] = ()
    satisfied_fields: tuple[DeliverableFieldKey, ...] = ()
    missing_fields: tuple[DeliverableFieldKey, ...] = ()
    invalid_fields: tuple[DeliverableFieldKey, ...] = ()
    unproven_fields: tuple[DeliverableFieldKey, ...] = ()
    unresolved_items: tuple[str, ...] = ()
    artifact_complete: bool = False
    assembly_errors: tuple[str, ...] = ()
    complete: bool = False
    observed_row_count: int = 0
    required_row_count: int = 0


class RevOpsMissionDeliverableRead(BaseModel):
    """Final RevOps V1 mission deliverable assembled from current read models."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    kind: Literal["revops_report"] = "revops_report"
    mission_id: uuid.UUID
    objective: str
    # Preserve typed non-prospect artifacts (for example web_page_observation)
    # in the durable read model so a completed mission is inspectable without
    # forcing every job into the prospect-shaped projection.
    artifacts: dict[str, Any] = Field(default_factory=dict)
    prospects: tuple[RevOpsProspectRead, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    approval_state: RevOpsApprovalStateRead
    effects: tuple[RevOpsEffectRead, ...] = ()
    evidence_references: tuple[RevOpsEvidenceReferenceRead, ...] = ()
    task_state: RevOpsTaskStateRead
    completion: RevOpsCompletionRead
    grants_execution_authority: Literal[False] = False


def _runtime_state_from_metadata(metadata: object) -> object | None:
    if not isinstance(metadata, dict):
        return None
    intake = metadata.get("mission_intake")
    if not isinstance(intake, dict):
        return None
    context = intake.get("context")
    if not isinstance(context, dict):
        return None
    composition = context.get("composition")
    if not isinstance(composition, dict):
        return None
    return composition.get(DELIVERABLE_RUNTIME_STATE_METADATA_KEY)


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip()))


def _handler_result(task: ExecutionTask) -> dict[str, Any]:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    result = metadata.get("handler_result")
    return dict(result) if isinstance(result, dict) else {}


def _task_action(task: ExecutionTask) -> str | None:
    result = _handler_result(task)
    action = _nonempty_text(result.get("action"))
    if action is not None:
        return action
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    invocation = metadata.get("tool_invocation")
    if not isinstance(invocation, dict):
        return None
    return _nonempty_text(invocation.get("action"))


def _validate_ownership(
    *,
    mission: Mission,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
    outcome_reviews: Sequence[OutcomeReview],
) -> None:
    for task in tasks:
        if task.tenant_id != mission.tenant_id or task.mission_id != mission.id:
            raise ValueError("execution task is not owned by the assembled tenant mission")
    for evidence in evidence_records:
        if evidence.tenant_id != mission.tenant_id or evidence.mission_id != mission.id:
            raise ValueError("evidence record is not owned by the assembled tenant mission")
    for review in outcome_reviews:
        if review.tenant_id != mission.tenant_id or review.mission_id != mission.id:
            raise ValueError("outcome review is not owned by the assembled tenant mission")


def _completion_read(
    *,
    state: Any,
    completion: DeliverableCompletion,
    assembly_errors: Sequence[str],
) -> RevOpsCompletionRead:
    satisfied: list[DeliverableFieldKey] = []
    missing: list[DeliverableFieldKey] = []
    invalid: list[DeliverableFieldKey] = []
    unproven: list[DeliverableFieldKey] = []
    observed_row_count = max((field.observed_rows for field in completion.fields), default=0)
    required_row_count = max((field.required_rows for field in completion.fields), default=0)
    for field in completion.fields:
        if field.status == "satisfied":
            satisfied.append(field.field_key)
        elif field.status == "missing_artifact":
            missing.append(field.field_key)
        elif field.status in {"invalid_artifact", "insufficient_rows"}:
            invalid.append(field.field_key)
        else:
            unproven.append(field.field_key)
    errors = tuple(dict.fromkeys(assembly_errors))
    return RevOpsCompletionRead(
        requested_fields=tuple(field.field_key for field in state.request.fields),
        satisfied_fields=tuple(satisfied),
        missing_fields=tuple(missing),
        invalid_fields=tuple(invalid),
        unproven_fields=tuple(unproven),
        unresolved_items=completion.unresolved_request_items,
        artifact_complete=completion.complete,
        assembly_errors=errors,
        complete=completion.complete and not errors,
        observed_row_count=observed_row_count,
        required_row_count=required_row_count,
    )


def _validated_artifacts(
    tasks: Sequence[ExecutionTask],
    *,
    assembly_errors: list[str],
) -> dict[str, MaterializedArtifact]:
    validated: dict[str, MaterializedArtifact] = {}
    for artifact in collect_materialized_artifacts(list(tasks)):
        if artifact.artifact_key in ARTIFACT_SCHEMAS_BY_KEY:
            validation = validate_materialized_artifact(artifact)
            if not validation.valid:
                assembly_errors.append(f"artifact {artifact.artifact_key!r} is invalid: {'; '.join(validation.errors)}")
                continue
        validated[artifact.artifact_key] = artifact
    return validated


def _identity_key(
    row: Mapping[str, Any],
    *,
    records: Mapping[str, dict[str, Any]],
    companies: Mapping[str, set[str]],
) -> tuple[str | None, str | None, str | None]:
    prospect_id = _nonempty_text(row.get("prospect_id"))
    company = _nonempty_text(row.get("company") or row.get("company_name"))
    if prospect_id is not None:
        return f"id:{prospect_id}", prospect_id, company
    if company is None:
        return None, None, None
    normalized_company = company.casefold()
    matches = companies.get(normalized_company, set())
    if len(matches) == 1:
        key = next(iter(matches))
        existing = records.get(key, {})
        return key, _nonempty_text(existing.get("prospect_id")), company
    return f"company:{normalized_company}", None, company


def _new_prospect(*, prospect_id: str | None, identity_company: str | None) -> dict[str, Any]:
    return {
        "prospect_id": prospect_id,
        "_identity_company": identity_company,
        "company_name": None,
        "website": None,
        "product_description": None,
        "research_summary": None,
        "sources": [],
        "observed_contacts": [],
        "qualification_evidence": None,
        "ajenda_relevance": None,
        "qualification_score": None,
        "qualification_reasons": (),
        "drafts": [],
        "_conflicts": set(),
    }


def _record_for_row(
    row: Mapping[str, Any],
    *,
    records: dict[str, dict[str, Any]],
    companies: dict[str, set[str]],
    assembly_errors: list[str],
    artifact_key: str,
) -> dict[str, Any] | None:
    key, prospect_id, company = _identity_key(row, records=records, companies=companies)
    if key is None:
        assembly_errors.append(f"artifact {artifact_key!r} contains a row without prospect identity")
        return None
    record = records.setdefault(key, _new_prospect(prospect_id=prospect_id, identity_company=company))
    if prospect_id is not None and record["prospect_id"] is None:
        record["prospect_id"] = prospect_id
    if company is not None:
        record["_identity_company"] = record["_identity_company"] or company
        companies[company.casefold()].add(key)
    return record


def _set_scalar(
    record: dict[str, Any],
    *,
    field: str,
    value: Any,
    identity: str,
    assembly_errors: list[str],
) -> None:
    if value is None or value == "" or value == () or value == [] or value == {}:
        return
    if field in record["_conflicts"]:
        return
    current = record[field]
    if current is None or current == () or current == []:
        record[field] = value
        return
    if current == value:
        return
    record[field] = None if field not in {"qualification_reasons"} else ()
    record["_conflicts"].add(field)
    assembly_errors.append(f"conflicting {field} values for prospect {identity!r}")


def _artifact_rows(artifacts: Mapping[str, MaterializedArtifact], artifact_key: str) -> list[dict[str, Any]]:
    artifact = artifacts.get(artifact_key)
    if artifact is None or not isinstance(artifact.payload, list):
        return []
    return [dict(item) for item in artifact.payload if isinstance(item, dict)]


def _draft_read(
    row: Mapping[str, Any],
    *,
    mission: Mission,
    document_artifacts: Mapping[str, Mapping[str, Any]],
    assembly_errors: list[str],
) -> RevOpsDraftRead:
    artifact_id = _nonempty_text(row.get("artifact_id"))
    document = document_artifacts.get(artifact_id, {}) if artifact_id is not None else {}
    if document:
        document_mission_id = _nonempty_text(document.get("mission_id"))
        if document_mission_id is not None and document_mission_id != str(mission.id):
            assembly_errors.append(f"draft artifact {artifact_id!r} is not owned by the assembled mission")
            document = {}
    raw_content = document.get("content")
    content: Mapping[str, Any] = raw_content if isinstance(raw_content, dict) else {}
    raw_status = _nonempty_text(document.get("review_status"))
    review_status = cast(
        Literal["pending", "approved", "rejected", "sent", "unresolved"],
        raw_status if raw_status in _DRAFT_REVIEW_STATUSES else "unresolved",
    )
    if artifact_id is not None and not document:
        assembly_errors.append(f"draft artifact {artifact_id!r} could not be resolved")
    return RevOpsDraftRead(
        artifact_id=artifact_id,
        prospect_id=_nonempty_text(row.get("prospect_id")),
        company_name=_nonempty_text(row.get("company")),
        recipient=_nonempty_text(content.get("to") or row.get("recipient")),
        subject=_nonempty_text(content.get("subject") or row.get("subject")),
        body=_nonempty_text(content.get("body") or content.get("draft")),
        review_status=review_status,
        recipient_bound=row.get("recipient_bound") is True,
    )


def _assemble_prospects(
    *,
    mission: Mission,
    artifacts: Mapping[str, MaterializedArtifact],
    document_artifacts: Mapping[str, Mapping[str, Any]],
    assembly_errors: list[str],
) -> tuple[RevOpsProspectRead, ...]:
    records: dict[str, dict[str, Any]] = {}
    companies: dict[str, set[str]] = defaultdict(set)

    verified_rows = _artifact_rows(artifacts, "verified_prospect_candidates")
    candidate_sources = (
        (("verified_prospect_candidates", verified_rows),)
        if verified_rows
        else (("prospect_candidates", _artifact_rows(artifacts, "prospect_candidates")),)
    )
    for artifact_key, rows in candidate_sources:
        for row in rows:
            record = _record_for_row(
                row,
                records=records,
                companies=companies,
                assembly_errors=assembly_errors,
                artifact_key=artifact_key,
            )
            if record is None:
                continue
            identity = record["prospect_id"] or record["_identity_company"] or "unknown"
            _set_scalar(
                record,
                field="company_name",
                value=_nonempty_text(row.get("company") or row.get("company_name")),
                identity=identity,
                assembly_errors=assembly_errors,
            )
            for field in ("website", "product_description", "research_summary"):
                _set_scalar(
                    record,
                    field=field,
                    value=_nonempty_text(row.get(field)),
                    identity=identity,
                    assembly_errors=assembly_errors,
                )
            for source in _string_tuple(row.get("sources")):
                if source not in record["sources"]:
                    record["sources"].append(source)
            for raw_contact in row.get("observed_contacts", []):
                if not isinstance(raw_contact, dict):
                    continue
                contact = RevOpsObservedContactRead(
                    kind=_nonempty_text(raw_contact.get("kind")),
                    value=_nonempty_text(raw_contact.get("value")),
                    source_url=_nonempty_text(raw_contact.get("source_url")),
                    real=raw_contact.get("real") is True,
                )
                if contact not in record["observed_contacts"]:
                    record["observed_contacts"].append(contact)

    for row in _artifact_rows(artifacts, "observed_contacts"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="observed_contacts",
        )
        if record is None:
            continue
        for source in _string_tuple(row.get("sources")):
            if source not in record["sources"]:
                record["sources"].append(source)
        identity = record["prospect_id"] or record["_identity_company"] or "unknown"
        _set_scalar(
            record,
            field="website",
            value=_nonempty_text(row.get("website")),
            identity=identity,
            assembly_errors=assembly_errors,
        )
        contact = RevOpsObservedContactRead(
            kind=_nonempty_text(row.get("kind")),
            value=_nonempty_text(row.get("value")),
            source_url=_nonempty_text(row.get("source_url")),
            real=row.get("real") is True,
        )
        if contact not in record["observed_contacts"]:
            record["observed_contacts"].append(contact)

    for row in _artifact_rows(artifacts, "qualified_prospects"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="qualified_prospects",
        )
        if record is None:
            continue
        identity = record["prospect_id"] or record["_identity_company"] or "unknown"
        raw_score = row.get("score")
        score = raw_score if isinstance(raw_score, int) and not isinstance(raw_score, bool) else None
        values = {
            "company_name": _nonempty_text(row.get("company")),
            "website": _nonempty_text(row.get("website") or row.get("url")),
            "product_description": _nonempty_text(row.get("product_description") or row.get("description")),
            "research_summary": _nonempty_text(row.get("research_summary")),
            "qualification_evidence": dict(row["qualification_evidence"])
            if isinstance(row.get("qualification_evidence"), dict)
            else None,
            "ajenda_relevance": _nonempty_text(row.get("ajenda_relevance")),
            "qualification_score": score,
            "qualification_reasons": _string_tuple(row.get("reasons")),
        }
        for field, value in values.items():
            _set_scalar(
                record,
                field=field,
                value=value,
                identity=identity,
                assembly_errors=assembly_errors,
            )
        for source in _string_tuple(row.get("sources")):
            if source not in record["sources"]:
                record["sources"].append(source)

    for row in _artifact_rows(artifacts, "introduction_drafts"):
        record = _record_for_row(
            row,
            records=records,
            companies=companies,
            assembly_errors=assembly_errors,
            artifact_key="introduction_drafts",
        )
        if record is None:
            continue
        draft = _draft_read(
            row,
            mission=mission,
            document_artifacts=document_artifacts,
            assembly_errors=assembly_errors,
        )
        if draft not in record["drafts"]:
            record["drafts"].append(draft)

    assembled: list[RevOpsProspectRead] = []
    for key in sorted(records):
        record = records[key]
        assembled.append(
            RevOpsProspectRead(
                prospect_id=record["prospect_id"],
                company_name=record["company_name"],
                website=record["website"],
                product_description=record["product_description"],
                research_summary=record["research_summary"],
                sources=tuple(record["sources"]),
                observed_contacts=tuple(record["observed_contacts"]),
                qualification_evidence=record["qualification_evidence"],
                ajenda_relevance=record["ajenda_relevance"],
                qualification_score=record["qualification_score"],
                qualification_reasons=tuple(record["qualification_reasons"]),
                drafts=tuple(record["drafts"]),
            )
        )
    return tuple(assembled)


def _task_approval(
    task: ExecutionTask,
    *,
    now: datetime,
) -> RevOpsTaskApprovalRead | None:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    constraints = metadata.get("execution_constraints")
    raw_grant = constraints.get("side_effect_authorization") if isinstance(constraints, dict) else None
    relevant = (
        task.requires_human_review or task.status == ExecutionTaskState.PENDING_REVIEW.value or raw_grant is not None
    )
    if not relevant:
        return None

    action = _task_action(task)
    if raw_grant is None:
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="pending",
        )
    if not isinstance(raw_grant, dict):
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="invalid",
        )

    if raw_grant.get("schema_version") == 2:
        try:
            grant = SideEffectAuthorizationV2.model_validate(raw_grant)
        except ValidationError:
            return RevOpsTaskApprovalRead(
                task_id=task.id,
                action=action,
                task_status=task.status,
                status="invalid",
            )
        approval_status: Literal["approved", "consumed", "expired", "revoked"]
        if grant.revoked_at is not None:
            approval_status = "revoked"
        elif task.status == ExecutionTaskState.COMPLETED.value:
            approval_status = "consumed"
        elif now >= grant.expires_at.astimezone(UTC):
            approval_status = "expired"
        else:
            approval_status = "approved"
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status=approval_status,
            grant_id=grant.grant_id,
            approved_by=grant.approved_by,
            expires_at=grant.expires_at,
        )

    try:
        legacy = SideEffectAuthorization.model_validate(raw_grant)
    except ValidationError:
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="invalid",
        )
    return RevOpsTaskApprovalRead(
        task_id=task.id,
        action=action,
        task_status=task.status,
        status="consumed" if task.status == ExecutionTaskState.COMPLETED.value else "approved",
        approved_by=legacy.approved_by,
    )


def _approval_state(
    *,
    prospects: Sequence[RevOpsProspectRead],
    tasks: Sequence[ExecutionTask],
    outcome_reviews: Sequence[OutcomeReview],
    now: datetime,
) -> RevOpsApprovalStateRead:
    draft_approvals = tuple(
        RevOpsDraftApprovalRead(artifact_id=draft.artifact_id, status=draft.review_status)
        for prospect in prospects
        for draft in prospect.drafts
    )
    task_approvals = tuple(
        approval
        for task in sorted(tasks, key=lambda item: str(item.id))
        if (approval := _task_approval(task, now=now)) is not None
    )
    reviews = tuple(
        RevOpsOutcomeReviewRead(
            review_id=review.id,
            review_status=review.review_status,
            review_decision=review.review_decision,
            human_approval_required=review.human_approval_required,
            human_approval_status=review.human_approval_status,
        )
        for review in sorted(outcome_reviews, key=lambda item: (item.created_at, str(item.id)))
    )
    draft_ready = all(item.status in {"approved", "sent"} for item in draft_approvals)
    task_ready = all(item.status in {"approved", "consumed"} for item in task_approvals)
    review_ready = all(
        not item.human_approval_required or item.human_approval_status in {"approved", "not_required"}
        for item in reviews
    )
    return RevOpsApprovalStateRead(
        draft_approvals=draft_approvals,
        task_approvals=task_approvals,
        outcome_reviews=reviews,
        all_required_approved=draft_ready and task_ready and review_ready,
    )


def _receipt_from_output(
    *,
    output: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any] | None:
    receipt: dict[str, Any] = {}
    for key in ("idempotency_key", "provider_message_id", "artifact_id", "post_id", "url", "id"):
        value = output.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            receipt[key] = value
    records_changed = result.get("records_changed")
    if isinstance(records_changed, list):
        normalized = [str(item) for item in records_changed if str(item).strip()]
        if normalized:
            receipt["records_changed"] = normalized
    real_response = output.get("real_response")
    if isinstance(real_response, dict) and isinstance(real_response.get("status_code"), int):
        receipt["provider_status_code"] = real_response["status_code"]
    return receipt or None


def _effects(
    *,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
) -> tuple[RevOpsEffectRead, ...]:
    evidence_by_task: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for evidence in evidence_records:
        if evidence.execution_task_id is not None:
            evidence_by_task[evidence.execution_task_id].append(evidence.id)

    effects: list[RevOpsEffectRead] = []
    for task in sorted(tasks, key=lambda item: str(item.id)):
        result = _handler_result(task)
        raw_class = result.get("side_effect_class")
        if not isinstance(raw_class, str):
            continue
        try:
            side_effect_class = SideEffectClass(raw_class)
        except ValueError:
            continue
        if not side_effect_class.has_side_effect:
            continue
        output = result.get("output")
        output = dict(output) if isinstance(output, dict) else {}
        real = output.get("real") is True
        receipt = _receipt_from_output(output=output, result=result) if real else None
        if not real:
            receipt_status: Literal["recorded", "missing", "simulated", "not_applicable"] = "simulated"
        elif receipt is None:
            receipt_status = "missing"
        else:
            receipt_status = "recorded"
        effects.append(
            RevOpsEffectRead(
                task_id=task.id,
                action=_task_action(task),
                side_effect_class=side_effect_class,
                task_status=task.status,
                status=_nonempty_text(output.get("status")) or task.status,
                real=real,
                provider=_nonempty_text(output.get("provider") or result.get("provider")),
                receipt_status=receipt_status,
                receipt=receipt,
                evidence_ids=tuple(sorted(evidence_by_task.get(task.id, []), key=str)),
            )
        )
    return tuple(effects)


def _limitations(
    *,
    tasks: Sequence[ExecutionTask],
    evidence_records: Sequence[EvidenceRecord],
    assembly_errors: Sequence[str],
) -> tuple[str, ...]:
    values: list[str] = list(assembly_errors)
    for task in sorted(tasks, key=lambda item: str(item.id)):
        result = _handler_result(task)
        for value in _string_tuple(result.get("limitations")):
            values.append(value)
        if task.status == ExecutionTaskState.BLOCKED.value and not result:
            values.append(
                f"task {task.id} is blocked without persisted handler output; external effect state may be ambiguous"
            )
    for evidence in evidence_records:
        provenance = evidence.provenance_metadata if isinstance(evidence.provenance_metadata, dict) else {}
        for value in _string_tuple(provenance.get("limitations")):
            values.append(value)
    return tuple(dict.fromkeys(values))


def assemble_revops_mission_deliverable(
    *,
    mission: Mission,
    tasks: Sequence[ExecutionTask],
    document_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    evidence_records: Sequence[EvidenceRecord] = (),
    outcome_reviews: Sequence[OutcomeReview] = (),
    now: datetime | None = None,
) -> RevOpsMissionDeliverableRead:
    """Assemble the current tenant-owned RevOps report without mutating runtime state."""

    _validate_ownership(
        mission=mission,
        tasks=tasks,
        evidence_records=evidence_records,
        outcome_reviews=outcome_reviews,
    )
    state = load_deliverable_runtime_state(_runtime_state_from_metadata(mission.metadata_json))
    if state is None:
        raise ValueError("mission deliverable runtime state is absent")
    request_fields = tuple(field.field_key for field in state.request.fields)
    projected_fields = tuple(binding.field_key for binding in state.projection.bindings)
    if projected_fields != request_fields:
        raise ValueError("mission deliverable runtime projection does not match its request")
    if state.projection.request_unresolved_items != state.request.unresolved_items:
        raise ValueError("mission deliverable runtime unresolved items do not match its request")

    assembly_errors: list[str] = []
    collected = collect_materialized_artifacts(list(tasks))
    artifacts = _validated_artifacts(tasks, assembly_errors=assembly_errors)
    completion = evaluate_deliverable_completion(state.projection, collected)
    prospects = _assemble_prospects(
        mission=mission,
        artifacts=artifacts,
        document_artifacts=document_artifacts or {},
        assembly_errors=assembly_errors,
    )
    evidence_reads = tuple(
        RevOpsEvidenceReferenceRead(
            evidence_id=evidence.id,
            execution_task_id=evidence.execution_task_id,
            evidence_type=evidence.evidence_type,
            evidence_source=evidence.evidence_source,
            summary=evidence.summary,
            confidence=evidence.confidence,
            collection_status=evidence.collection_status,
        )
        for evidence in sorted(evidence_records, key=lambda item: (item.created_at, str(item.id)))
    )
    status_counts = Counter(task.status for task in tasks)
    task_state = RevOpsTaskStateRead(
        task_count=len(tasks),
        statuses=dict(sorted(status_counts.items())),
        all_terminal=bool(tasks) and all(task.status in _TERMINAL_TASK_STATES for task in tasks),
        all_succeeded=bool(tasks) and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks),
    )
    effective_now = now or datetime.now(UTC)
    if effective_now.tzinfo is None:
        raise ValueError("assembler now must be timezone-aware")
    approval_state = _approval_state(
        prospects=prospects,
        tasks=tasks,
        outcome_reviews=outcome_reviews,
        now=effective_now.astimezone(UTC),
    )
    limitations = _limitations(
        tasks=tasks,
        evidence_records=evidence_records,
        assembly_errors=assembly_errors,
    )
    return RevOpsMissionDeliverableRead(
        mission_id=mission.id,
        objective=mission.objective,
        artifacts={artifact_key: artifact.payload for artifact_key, artifact in artifacts.items()},
        prospects=prospects,
        assumptions=(),
        limitations=limitations,
        approval_state=approval_state,
        effects=_effects(tasks=tasks, evidence_records=evidence_records),
        evidence_references=evidence_reads,
        task_state=task_state,
        completion=_completion_read(
            state=state,
            completion=completion,
            assembly_errors=assembly_errors,
        ),
    )
