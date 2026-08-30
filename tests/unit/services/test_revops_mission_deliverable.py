from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)
from backend.services.mission_composition.revops_deliverable import assemble_revops_mission_deliverable
from backend.services.tools.schemas import ToolInvocation, tool_invocation_sha256

MISSION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
TENANT_ID = "tenant-revops"


def _metadata(instruction: str) -> dict[str, object]:
    request = extract_deliverable_request(instruction)
    assert request is not None
    state = build_deliverable_runtime_state(request)
    assert state is not None
    return {
        "mission_intake": {
            "context": {
                "composition": {
                    DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                }
            }
        }
    }


def _mission(instruction: str) -> Mission:
    mission = Mission(
        id=MISSION_ID,
        tenant_id=TENANT_ID,
        objective="Produce an artifact-backed RevOps report.",
        status="running",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json=_metadata(instruction),
    )
    mission.created_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    mission.updated_at = mission.created_at
    return mission


def _task(
    *,
    task_id: int,
    artifact: str,
    payload: object,
    status: str = ExecutionTaskState.COMPLETED.value,
    handler_fields: dict[str, object] | None = None,
    metadata_fields: dict[str, object] | None = None,
    requires_human_review: bool = False,
) -> ExecutionTask:
    result = {
        "handler": "artifact-test",
        "status": "completed",
        "output": {artifact: payload},
        **(handler_fields or {}),
    }
    metadata = {
        "expected_output_contract": {"artifact": artifact},
        "handler_result": result,
        **(metadata_fields or {}),
    }
    task = ExecutionTask(
        id=uuid.UUID(int=task_id),
        tenant_id=TENANT_ID,
        mission_id=MISSION_ID,
        title=f"Task {task_id}",
        description="Materialize one RevOps artifact.",
        status=status,
        metadata_json=metadata,
        requires_human_review=requires_human_review,
    )
    task.created_at = datetime(2026, 8, 30, 12, task_id, tzinfo=UTC)
    task.updated_at = task.created_at
    return task


def _artifact_tasks() -> list[ExecutionTask]:
    return [
        _task(
            task_id=1,
            artifact="prospect_candidates",
            payload=[
                {
                    "prospect_id": "prospect-1",
                    "company": "Acme HVAC",
                    "website": "https://acme.example",
                    "product_description": "Residential HVAC installation and service.",
                    "research_summary": "Acme serves residential customers in Phoenix.",
                    "sources": ["https://acme.example"],
                }
            ],
        ),
        _task(
            task_id=2,
            artifact="observed_contacts",
            payload=[
                {
                    "prospect_id": "prospect-1",
                    "company": "Acme HVAC",
                    "kind": "email",
                    "value": "owner@acme.example",
                    "source_url": "https://acme.example/contact",
                    "real": True,
                    "sources": ["https://acme.example/contact"],
                }
            ],
        ),
        _task(
            task_id=3,
            artifact="qualified_prospects",
            payload=[
                {
                    "prospect_id": "prospect-1",
                    "company": "Acme HVAC",
                    "score": 84,
                    "reasons": ["verified business fit"],
                    "qualification_evidence": {
                        "qualification_dimensions": {"business_fit": 10},
                        "qualification_reasons": ["verified business fit"],
                        "source_references": ["https://acme.example"],
                    },
                    "ajenda_relevance": "Ajenda may be relevant to the observed estimate follow-up workflow.",
                }
            ],
        ),
        _task(
            task_id=4,
            artifact="introduction_drafts",
            payload=[
                {
                    "prospect_id": "prospect-1",
                    "company": "Acme HVAC",
                    "recipient": "owner@acme.example",
                    "subject": "Introduction — Acme HVAC",
                    "artifact_id": "pitch_email-draft-1",
                    "recipient_bound": True,
                }
            ],
        ),
    ]


def test_assembler_builds_complete_report_from_typed_runtime_artifacts() -> None:
    mission = _mission(
        "Return company name, website, product description, qualification evidence, "
        "qualification reasons, Ajenda relevance, qualification score, research summary, sources, and drafts."
    )
    tasks = _artifact_tasks()
    evidence = EvidenceRecord(
        id=uuid.UUID(int=100),
        tenant_id=TENANT_ID,
        mission_id=MISSION_ID,
        execution_task_id=tasks[2].id,
        evidence_type="action_result",
        evidence_source="tool.invoke.sales.qualify",
        summary="Qualified Acme from observed evidence.",
        structured_payload={},
        artifact_references=[],
        provenance_metadata={"limitations": ["Public-page coverage is bounded."]},
        trust_signal={},
        confidence=0.8,
        collection_status="collected",
        schema_version=1,
    )
    evidence.created_at = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    evidence.updated_at = evidence.created_at

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=tasks,
        document_artifacts={
            "pitch_email-draft-1": {
                "mission_id": str(MISSION_ID),
                "review_status": "approved",
                "content": {
                    "to": "owner@acme.example",
                    "subject": "Introduction — Acme HVAC",
                    "body": "Hello Acme team.",
                },
            }
        },
        evidence_records=[evidence],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.completion.artifact_complete is True
    assert report.completion.complete is True
    assert report.task_state.all_succeeded is True
    assert report.task_state.task_count == 4
    assert report.assumptions == ()
    assert report.limitations == ("Public-page coverage is bounded.",)
    assert report.approval_state.all_required_approved is True
    assert report.grants_execution_authority is False

    assert len(report.prospects) == 1
    prospect = report.prospects[0]
    assert prospect.prospect_id == "prospect-1"
    assert prospect.company_name == "Acme HVAC"
    assert prospect.website == "https://acme.example"
    assert prospect.product_description == "Residential HVAC installation and service."
    assert prospect.research_summary == "Acme serves residential customers in Phoenix."
    assert prospect.sources == ("https://acme.example", "https://acme.example/contact")
    assert prospect.observed_contacts[0].value == "owner@acme.example"
    assert prospect.qualification_score == 84
    assert prospect.qualification_reasons == ("verified business fit",)
    assert prospect.drafts[0].review_status == "approved"
    assert prospect.drafts[0].body == "Hello Acme team."
    assert report.evidence_references[0].evidence_id == evidence.id


def test_task_success_does_not_make_partial_or_unproven_deliverable_complete() -> None:
    mission = _mission("Return company name, drafts, assumptions, and limitations.")
    qualified = _artifact_tasks()[2]

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[qualified],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.task_state.all_succeeded is True
    assert report.completion.satisfied_fields == ("company_name",)
    assert report.completion.missing_fields == ("drafts",)
    assert report.completion.unproven_fields == ("assumptions", "limitations")
    assert report.completion.complete is False
    assert report.assumptions == ()


def test_conflicting_duplicate_artifacts_are_not_assembled_or_completed() -> None:
    mission = _mission("Return company name.")
    first = _artifact_tasks()[2]
    conflicting = _task(
        task_id=5,
        artifact="qualified_prospects",
        payload=[
            {
                "prospect_id": "prospect-1",
                "company": "Different Company",
                "score": 84,
                "reasons": ["conflict"],
                "qualification_evidence": {"source_references": ["https://other.example"]},
                "ajenda_relevance": "Different relevance.",
            }
        ],
    )

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[first, conflicting],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.prospects == ()
    assert report.completion.missing_fields == ("company_name",)
    assert report.completion.complete is False
    assert report.task_state.all_succeeded is True


def test_assembler_exposes_consumed_approval_real_effect_and_receipt() -> None:
    mission = _mission("Return company name.")
    qualified = _artifact_tasks()[2]
    invocation = ToolInvocation(
        action="gtm.email_send",
        input={"to": "owner@acme.example", "subject": "Hello", "body": "Hi"},
        idempotency_key="mission-send-1",
    )
    approved_at = datetime(2026, 8, 30, 13, 0, tzinfo=UTC)
    effect = _task(
        task_id=5,
        artifact="sent_messages",
        payload=[
            {
                "to": "owner@acme.example",
                "subject": "Hello",
                "status": "sent",
                "real": True,
                "provider": "gmail_api",
                "idempotency_key": "mission-send-1",
                "provider_message_id": "msg-1",
            }
        ],
        handler_fields={
            "handler": "tool.invoke",
            "action": "gtm.email_send",
            "provider": "external_email",
            "side_effect_class": "external_send",
            "records_changed": [],
            "output": {
                "sent_messages": [
                    {
                        "to": "owner@acme.example",
                        "subject": "Hello",
                        "status": "sent",
                        "real": True,
                        "provider": "gmail_api",
                        "idempotency_key": "mission-send-1",
                        "provider_message_id": "msg-1",
                    }
                ],
                "status": "sent",
                "real": True,
                "provider": "gmail_api",
                "idempotency_key": "mission-send-1",
                "provider_message_id": "msg-1",
            },
        },
        metadata_fields={
            "tool_invocation": invocation.model_dump(mode="json"),
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 2,
                    "grant_id": str(uuid.UUID(int=200)),
                    "tenant_id": TENANT_ID,
                    "task_id": str(uuid.UUID(int=5)),
                    "allowed_action": "gtm.email_send",
                    "invocation_sha256": tool_invocation_sha256(invocation),
                    "reason": "human_review_approved",
                    "approved_by": "operator-1",
                    "approved_at": approved_at.isoformat(),
                    "expires_at": (approved_at + timedelta(hours=1)).isoformat(),
                    "revoked_at": None,
                }
            },
        },
        requires_human_review=True,
    )
    evidence = EvidenceRecord(
        id=uuid.UUID(int=201),
        tenant_id=TENANT_ID,
        mission_id=MISSION_ID,
        execution_task_id=effect.id,
        evidence_type="action_result_evidence",
        evidence_source="gtm_actions",
        summary="External email sent via Gmail API.",
        structured_payload={},
        artifact_references=[],
        provenance_metadata={},
        trust_signal={"side_effect_class": "external_send"},
        confidence=1.0,
        collection_status="collected",
        schema_version=1,
    )
    evidence.created_at = datetime(2026, 8, 30, 13, 10, tzinfo=UTC)
    evidence.updated_at = evidence.created_at
    review = OutcomeReview(
        id=uuid.UUID(int=202),
        tenant_id=TENANT_ID,
        mission_id=MISSION_ID,
        reviewed_success_criteria=[],
        evidence_references=[{"evidence_id": str(evidence.id)}],
        review_status="completed",
        review_decision="accepted",
        reviewer_type="operator",
        reviewer_source="operator-1",
        review_summary="Approved effect outcome.",
        structured_findings=[],
        trust_signal={},
        unresolved_gaps=[],
        recommended_next_actions=[],
        human_approval_required=True,
        human_approval_status="approved",
        schema_version=1,
    )
    review.created_at = datetime(2026, 8, 30, 13, 20, tzinfo=UTC)
    review.updated_at = review.created_at

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[qualified, effect],
        evidence_records=[evidence],
        outcome_reviews=[review],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.completion.complete is True
    assert report.approval_state.task_approvals[0].status == "consumed"
    assert report.approval_state.all_required_approved is True
    assert report.effects[0].real is True
    assert report.effects[0].receipt_status == "recorded"
    assert report.effects[0].receipt == {
        "idempotency_key": "mission-send-1",
        "provider_message_id": "msg-1",
    }
    assert report.effects[0].evidence_ids == (evidence.id,)


def test_simulated_effect_is_visible_but_never_reported_as_real_receipt() -> None:
    mission = _mission("Return company name.")
    qualified = _artifact_tasks()[2]
    simulated = _task(
        task_id=5,
        artifact="sent_messages",
        payload=[{"status": "simulated", "real": False}],
        handler_fields={
            "handler": "tool.invoke",
            "action": "gtm.email_send",
            "provider": "external_email",
            "side_effect_class": "external_send",
            "output": {
                "sent_messages": [{"status": "simulated", "real": False}],
                "status": "simulated",
                "real": False,
                "provider": "external_email",
            },
        },
    )

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[qualified, simulated],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.effects[0].real is False
    assert report.effects[0].receipt_status == "simulated"
    assert report.effects[0].receipt is None


def test_deliverable_can_be_complete_when_an_unrelated_task_failed() -> None:
    mission = _mission("Return company name.")
    qualified = _artifact_tasks()[2]
    failed = _task(
        task_id=5,
        artifact="sent_messages",
        payload=[],
        status=ExecutionTaskState.FAILED.value,
    )

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[qualified, failed],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.completion.complete is True
    assert report.task_state.all_terminal is True
    assert report.task_state.all_succeeded is False


def test_unresolved_draft_suppresses_final_completion_without_rewriting_artifact_completion() -> None:
    mission = _mission("Return drafts.")
    draft_task = _artifact_tasks()[3]

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[draft_task],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.completion.artifact_complete is True
    assert report.completion.complete is False
    assert report.prospects[0].drafts[0].review_status == "unresolved"
    assert report.limitations == ("draft artifact 'pitch_email-draft-1' could not be resolved",)


def test_real_effect_without_durable_identifiers_has_missing_receipt() -> None:
    mission = _mission("Return company name.")
    qualified = _artifact_tasks()[2]
    effect = _task(
        task_id=5,
        artifact="sent_messages",
        payload=[{"status": "sent", "real": True}],
        handler_fields={
            "handler": "tool.invoke",
            "action": "gtm.email_send",
            "provider": "external_email",
            "side_effect_class": "external_send",
            "output": {
                "sent_messages": [{"status": "sent", "real": True}],
                "status": "sent",
                "real": True,
                "provider": "gmail_api",
            },
        },
    )

    report = assemble_revops_mission_deliverable(
        mission=mission,
        tasks=[qualified, effect],
        now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
    )

    assert report.effects[0].real is True
    assert report.effects[0].receipt_status == "missing"
    assert report.effects[0].receipt is None


def test_assembler_rejects_runtime_projection_drift() -> None:
    mission = _mission("Return company name and website.")
    state = mission.metadata_json["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    state["projection"]["bindings"].reverse()

    with pytest.raises(ValueError, match="projection does not match"):
        assemble_revops_mission_deliverable(
            mission=mission,
            tasks=[],
            now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        )


def test_assembler_rejects_cross_tenant_inputs_and_absent_runtime_state() -> None:
    mission = _mission("Return company name.")
    foreign = _artifact_tasks()[2]
    foreign.tenant_id = "foreign-tenant"

    with pytest.raises(ValueError, match="execution task is not owned"):
        assemble_revops_mission_deliverable(
            mission=mission,
            tasks=[foreign],
            now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        )

    mission.metadata_json = {"mission_intake": {}}
    with pytest.raises(ValueError, match="runtime state is absent"):
        assemble_revops_mission_deliverable(
            mission=mission,
            tasks=[],
            now=datetime(2026, 8, 30, 14, 0, tzinfo=UTC),
        )
