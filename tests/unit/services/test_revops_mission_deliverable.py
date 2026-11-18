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
from backend.services.mission_composition.deliverable_runtime_read_model import refresh_deliverable_completion_metadata
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
    deliverable_minimum_rows,
)
from backend.services.mission_composition.revops_deliverable import assemble_revops_mission_deliverable
from backend.services.mission_composition.service import MissionCompositionService, _runtime_deliverable_request
from backend.services.tools.local_records import build_local_record_provider
from backend.services.tools.record_store import LocalRecordStoreAdapter
from backend.services.tools.sales_action_records import record_search
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation, tool_invocation_sha256
from backend.services.worker_runtime_contracts import _validate_declared_output_contract

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


@pytest.mark.parametrize(
    ("upcoming", "effective_start", "has_more", "expected_complete"),
    [
        (True, "2026-11-17T07:00:00+00:00", False, True),
        (True, None, False, False),
        (True, "invalid", False, False),
        (True, "2026-11-17T07:00:00+00:00", True, False),
        (False, None, None, False),
    ],
)
def test_calendar_readback_preserves_scope_and_pagination(
    upcoming: bool, effective_start: str | None, has_more: bool | None, expected_complete: bool
) -> None:
    mission = _mission("Return company name.")
    mission.objective = "Read my Google Calendar for upcoming events."
    mission.metadata_json = {}
    events = [{"id": "event-1"}]
    task = _task(
        task_id=1,
        artifact="calendar_events",
        payload=events,
        handler_fields={
            "output": {
                "calendar_events": events,
                "real": True,
                "effective_start": effective_start,
                "has_more": has_more,
            }
        },
        metadata_fields={"tool_invocation": {"action": "google_calendar.events_read", "input": {"upcoming": upcoming}}},
    )
    result = assemble_revops_mission_deliverable(mission=mission, tasks=[task])
    assert result.artifacts["calendar_events"] == events
    assert result.completion.complete is expected_complete
    assert result.result_semantics["source_observations"][0]["has_more"] is has_more
    assert result.grants_execution_authority is False


def test_email_reference_readback_is_visible_but_not_a_complete_message_deliverable() -> None:
    mission = _mission("Return company name.")
    mission.metadata_json = {}
    task = _task(
        task_id=1,
        artifact="email_messages",
        payload=[{"id": "m1", "thread_id": "t1", "snippet": None}],
        metadata_fields={"tool_invocation": {"action": "gtm.email_check"}},
    )
    result = assemble_revops_mission_deliverable(mission=mission, tasks=[task])
    assert result.artifacts["email_messages"][0]["id"] == "m1"
    assert not result.completion.complete
    assert not result.completion.artifact_complete
    assert "message content was not retrieved" in result.limitations[0].lower()
    assert not result.grants_execution_authority
    assert result.result_semantics["source_observations"][0]["real"] is None
    assert result.result_semantics["source_observations"][0]["retrieval_scope"] == "unknown"


def test_missing_runtime_state_does_not_accept_unrelated_email_artifact() -> None:
    mission = _mission("Return company name.")
    mission.metadata_json = {}
    task = _task(task_id=1, artifact="email_messages", payload=[{"id": "m1"}])
    with pytest.raises(ValueError, match="runtime state is absent"):
        assemble_revops_mission_deliverable(mission=mission, tasks=[task])


def test_email_reference_readback_keeps_simulation_visible() -> None:
    mission = _mission("Return company name.")
    mission.metadata_json = {}
    task = _task(
        task_id=1,
        artifact="email_messages",
        payload=[{"id": "sim-1"}],
        handler_fields={"output": {"email_messages": [{"id": "sim-1"}], "real": False, "retrieval_scope": "simulated"}},
        metadata_fields={"tool_invocation": {"action": "gtm.email_check"}},
    )
    result = assemble_revops_mission_deliverable(mission=mission, tasks=[task])
    assert result.result_semantics["source_observations"][0]["real"] is False
    assert result.result_semantics["source_observations"][0]["retrieval_scope"] == "simulated"


def test_email_reference_readback_rejects_malformed_or_conflicting_artifacts() -> None:
    mission = _mission("Return company name.")
    mission.metadata_json = {}

    def email_task(task_id: int, payload: object) -> ExecutionTask:
        return _task(
            task_id=task_id,
            artifact="email_messages",
            payload=payload,
            metadata_fields={"tool_invocation": {"action": "gtm.email_check"}},
        )

    with pytest.raises(ValueError, match="email reference artifact is invalid"):
        assemble_revops_mission_deliverable(mission=mission, tasks=[email_task(1, [{"thread_id": "t1"}])])
    with pytest.raises(ValueError, match="runtime state is absent"):
        assemble_revops_mission_deliverable(
            mission=mission, tasks=[email_task(1, [{"id": "m1"}]), email_task(2, [{"id": "m2"}])]
        )


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


def test_assembler_preserves_proven_valid_empty_public_research_artifacts() -> None:
    """A completed evidence-backed empty outcome remains operator-visible."""

    mission = _mission("Return company name.")
    valid_empty = {
        "classification": "valid_empty",
        "reason": "completed public research produced no verified prospects",
    }
    tasks = [
        _task(
            task_id=1,
            artifact="verified_prospect_candidates",
            payload=[],
            handler_fields={"output": {"verified_prospect_candidates": [], "valid_empty_result": valid_empty}},
        ),
        _task(
            task_id=2,
            artifact="qualified_prospects",
            payload=[],
            handler_fields={"output": {"qualified_prospects": [], "valid_empty_result": valid_empty}},
        ),
    ]

    report = assemble_revops_mission_deliverable(mission=mission, tasks=tasks)

    assert report.artifacts == {
        "qualified_prospects": [],
        "verified_prospect_candidates": [],
    }
    assert report.prospects == ()
    assert report.completion.complete is False
    assert report.completion.assembly_errors == ()


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
    assert report.result_semantics["completion_scope"] == "requested_deliverable"

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


def test_assembler_projects_company_name_from_research_candidates() -> None:
    mission = _mission("Return website, research summary, and sources.")
    task = _task(
        task_id=11,
        artifact="prospect_candidates",
        payload=[
            {
                "prospect_id": "prospect-research-1",
                "company": "Research Only HVAC",
                "website": "https://research-only.example",
                "product_description": "HVAC services.",
                "research_summary": "A research candidate.",
                "sources": ["https://research-only.example"],
            }
        ],
    )

    report = assemble_revops_mission_deliverable(mission=mission, tasks=[task])

    assert report.completion.complete is True
    assert report.prospects[0].company_name == "Research Only HVAC"


def test_verified_candidates_replace_raw_discovery_rows_in_deliverable() -> None:
    mission = _mission("Return company name and website.")
    raw = _task(
        task_id=12,
        artifact="prospect_candidates",
        payload=[
            {
                "prospect_id": "raw-1",
                "company": "Directory Listing",
                "website": "https://directory.example",
                "product_description": "HVAC directory listing.",
                "research_summary": "Raw listing.",
                "sources": ["https://directory.example"],
            },
            {
                "prospect_id": "raw-2",
                "company": "Raw Company",
                "website": "https://raw.example",
                "product_description": "HVAC service.",
                "research_summary": "Raw company.",
                "sources": ["https://raw.example"],
            },
        ],
    )
    verified = _task(
        task_id=13,
        artifact="verified_prospect_candidates",
        payload=[
            {
                "prospect_id": "verified-1",
                "company": "Verified HVAC",
                "website": "https://verified.example",
                "source": "public_search",
                "identity_status": "verified",
                "real": True,
                "identity_evidence_urls": ["https://verified.example/about"],
                "sources": ["https://verified.example"],
                "research_summary": "Verified HVAC serves Dallas.",
                "product_description": "HVAC service.",
            }
        ],
    )

    report = assemble_revops_mission_deliverable(mission=mission, tasks=[raw, verified])

    assert [item.prospect_id for item in report.prospects] == ["verified-1"]

    # Invalid verification evidence must not promote raw discovery rows into
    # the verified deliverable or silently bypass the public identity contract.
    verified.metadata_json["handler_result"]["output"]["verified_prospect_candidates"][0]["identity_evidence_urls"] = []
    invalid_report = assemble_revops_mission_deliverable(mission=mission, tasks=[raw, verified])
    assert invalid_report.prospects == ()
    assert any("identity_evidence_urls" in error for error in invalid_report.completion.assembly_errors)
    assert invalid_report.completion.complete is False


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


@pytest.mark.parametrize(
    ("count_scope", "phrase", "expected_names", "expected_complete"),
    [
        ("up to three", "Ajenda Test Customer", ["Cedar Supply", "Mesa Fabrication", "Ridge Logistics"], True),
        ("up to three", "Ajenda Test Customer - Cedar", ["Cedar Supply"], True),
        ("up to three", "Ajenda Test Customer - No Match 699", [], True),
        ("three", "Ajenda Test Customer - No Match 699", [], False),
    ],
)
def test_composed_internal_crm_search_materializes_the_requested_result(
    count_scope: str, phrase: str, expected_names: list[str], expected_complete: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    instruction = (
        f"In Ajenda\u2019s internal CRM, find {count_scope} account records whose names contain “{phrase}”. "
        "Return only their names. If none match, say so. Do not modify records, contact anyone, or use external sources."
    )
    record = MissionCompositionService(db=None).compose(tenant_id=TENANT_ID, instruction=instruction)
    assert record.ready_to_start, record.clarifications
    assert record.allowed_actions == ["record.search"]
    assert len(record.planned_steps) == 1
    step = record.planned_steps[0]
    assert step.tool_input == {"record_type": "account", "query": phrase, "query_field": "name", "limit": 3}
    requests = _runtime_deliverable_request(record.intent)
    assert requests is not None and not requests.unresolved_items
    assert [field.field_key for field in requests.fields] == ["company_name"]
    mission = _mission("Return company name.")
    state = build_deliverable_runtime_state(requests, minimum_rows=deliverable_minimum_rows(record.intent))
    mission.metadata_json = {
        "mission_intake": {"context": {"composition": {DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state}}}
    }

    records = {"decoy": {"id": "decoy", "name": "Other company", "description": phrase}}
    for name in ("Cedar Supply", "Mesa Fabrication", "Ridge Logistics"):
        records[name] = {"id": name, "name": f"Ajenda Test Customer - {name}"}
    provider = build_local_record_provider(
        {
            TENANT_ID: {"account": records},
            "other-tenant": {"account": {"foreign": {"id": "foreign", "name": phrase}}},
        }
    )
    monkeypatch.setattr(
        "backend.services.tools.sales_action_records._provider", lambda _: LocalRecordStoreAdapter(provider)
    )
    invocation = ToolInvocation(action=step.action_name, input=step.tool_input)
    action = record_search(
        invocation,
        ActionRuntimeContext(
            tenant_id=TENANT_ID, mission_id=MISSION_ID, task_id=uuid.UUID(int=1), worker_id="worker", lease_id="lease"
        ),
    )
    rows = action.output["crm_records"]
    assert [row["name"] for row in rows] == [f"Ajenda Test Customer - {name}" for name in expected_names]
    task = _task(
        task_id=1,
        artifact="crm_records",
        payload=rows,
        handler_fields={"output": action.output},
        metadata_fields={"tool_invocation": invocation.model_dump(mode="json")},
    )
    _validate_declared_output_contract(task, {"output": action.output})
    mission.metadata_json, completion = refresh_deliverable_completion_metadata(mission.metadata_json, [task])
    assert completion is not None and completion.complete == expected_complete
    report = assemble_revops_mission_deliverable(mission=mission, tasks=[task])
    assert report.artifacts["crm_records"] == rows
    assert report.completion.complete == expected_complete
    assert report.task_state.all_succeeded

    if not rows:
        # The same receipt cannot prove a different filter or an unexecuted search.
        task.metadata_json["tool_invocation"]["input"]["query"] = "Changed query"
        with pytest.raises(ValueError, match="must attest"):
            _validate_declared_output_contract(task, {"output": action.output})
        invalid = assemble_revops_mission_deliverable(mission=mission, tasks=[task])
        assert not invalid.completion.complete

        bare_output = {"record_type": "account", "count": 0, "records": [], "crm_records": []}
        with pytest.raises(ValueError, match="must attest"):
            _validate_declared_output_contract(task, {"output": bare_output})
