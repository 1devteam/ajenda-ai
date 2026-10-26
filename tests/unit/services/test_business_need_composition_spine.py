"""Assessment-to-composition tests for the existing intelligence spine.

These are deliberately composition-only proofs: a tenant-owned need
assessment may reach the existing decision action, but cannot issue runtime
authority or turn an unresolved/contradicted response into support.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.api.routes.mission_composition import ComposeMissionRequest
from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.plan_compiler import compile_planned_steps
from backend.services.mission_composition.service import MissionCompositionError, MissionCompositionService
from backend.services.operating_charter import default_operating_charter
from backend.services.tools.knowledge_actions import KnowledgeInformedDecisionSupportInput
from backend.services.tools.schemas import DecisionRecommendInput


def _assessment_context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "assessment_id": "0a3cfa70-1df6-4de6-a042-5e7b344b10d8",
        "need_id": "need-customer-acquisition",
        "need_revision": 3,
        "condition_summary": "Customer acquisition is below the approved target.",
        "candidate_responses": [
            {
                "response_key": "improve_lead_qualification",
                "summary": "Investigate lead quality before changing spend.",
                "evidence_status": "supported",
                "knowledge_support_status": "not_provided",
                "dependencies": ["current funnel-stage measurements"],
                "assumptions": [],
                "tradeoffs": ["delays a campaign decision"],
            },
            {
                "response_key": "increase_advertising",
                "summary": "Increase advertising spend.",
                "evidence_status": "conflicted",
                "knowledge_support_status": "supports",
                "dependencies": [],
                "assumptions": [],
                "tradeoffs": [],
            },
        ],
        "causes": [
            {
                "cause_key": "lead_quality",
                "summary": "Lead quality may be insufficient.",
                "status": "unresolved",
            }
        ],
        "information_gaps": ["funnel-stage conversion measurements"],
        "supporting_observation_ids": ["a5f82290-eb51-4b9f-a0c8-b1a54a70d6be"],
        "contradictory_observation_ids": ["bf0b6c7a-fb5e-48ff-8667-9f4f5b62baba"],
        "knowledge_epistemic_limits": [],
        "subject_references": [],
        "objective_reference": {"objective_key": "customer_acquisition"},
        "evaluated_at": "2026-10-25T04:00:00+00:00",
    }


def _baseline_measurement() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("3ef674e6-b7b7-4c7e-b48a-18361ec2f9cf"),
        objective_key="customer_acquisition",
        metric="qualified_conversion",
        subject_references=[{"schema_version": 1, "object_type": "organization", "object_id": "customer-1"}],
        observed_at=datetime(2026, 10, 25, 3, 0, tzinfo=UTC),
        source_content_fingerprint="sha256:" + "b" * 64,
    )


def test_referenced_need_review_is_interpretable_only_with_validated_assessment_context() -> None:
    instruction = "Review the referenced business need assessment and recommend the next action."

    without_reference = interpret_instruction(instruction)
    with_reference = interpret_instruction(instruction, business_need_assessment_available=True)

    assert "review_business_need" not in without_reference.requested_outcomes
    assert not without_reference.interpretation_ready
    assert with_reference.requested_outcomes == ["review_business_need"]
    assert with_reference.interpretation_ready
    assert all(clause.status != "unmatched" for clause in with_reference.interpreted_clauses)


def test_assessment_context_routes_existing_decision_owner_without_research_or_execution() -> None:
    intent = interpret_instruction(
        "Use the approved business profile and recommend the next action.",
        profile_context={"profile_id": "profile-1", "business_name": "Example"},
    ).model_copy(
        update={
            "context_requirements": [
                "business_profile",
                "decision_support_requested",
                "business_need_assessment_context",
            ]
        }
    )

    jobs = route_jobs_for_intent(intent)

    assert "business.review_need" in {job.job_key for job in jobs}
    assert "intelligence.advise_next" not in {job.job_key for job in jobs}
    assert "research.observe_sources" not in {job.job_key for job in jobs}
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    assert missing == []
    selected = [item for item in selections if item.selection_status == "selected"]
    assert any(
        item.job_key == "business.review_need" and item.action_name == "decision.recommend_next_action"
        for item in selected
    )
    assert all(
        item.side_effect_class not in {"internal_write", "external_write", "external_send", "external_publish"}
        for item in selected
    )


def test_assessment_context_builds_existing_decision_input_without_promoting_conflict() -> None:
    intent = interpret_instruction("Use the approved business profile and recommend the next action.").model_copy(
        update={"context_requirements": ["business_need_assessment_context"]}
    )

    payload = build_action_input(
        action_name="decision.recommend_next_action",
        intent=intent,
        business_need_assessment_context=_assessment_context(),
    )
    validated = DecisionRecommendInput.model_validate(payload)

    assert [option.option_id for option in validated.options] == [
        "improve_lead_qualification",
        "increase_advertising",
    ]
    assert [fact.supports_option_ids for fact in validated.evidence] == [["improve_lead_qualification"]]
    assert validated.context["assessment_evidence_class"] == "derived_noncanonical"
    assert "Capability availability does not determine whether a response is justified." in validated.constraints


def test_compiled_assessment_review_carries_the_context_into_the_existing_runtime_input_contract() -> None:
    intent = interpret_instruction("Use the approved business profile and recommend the next action.").model_copy(
        update={"context_requirements": ["business_need_assessment_context"]}
    )
    selections, _ = resolve_jobs(route_jobs_for_intent(intent), intent=intent, charter=default_operating_charter())

    steps = compile_planned_steps(
        selections,
        intent=intent,
        business_need_assessment_context=_assessment_context(),
    )

    step = next(item for item in steps if item.job_key == "business.review_need")
    assert step.action_name == "decision.recommend_next_action"
    assert step.tool_input["context"]["assessment_reference"]["need_id"] == "need-customer-acquisition"
    assert step.tool_input["context"]["assessment_evidence_class"] == "derived_noncanonical"


def test_semantically_complete_assessment_routes_existing_qualified_knowledge_decision_owner() -> None:
    context = _assessment_context()
    context["subject_references"] = [{"schema_version": 1, "object_type": "organization", "object_id": "1devteam"}]
    context["evaluated_at"] = datetime(2026, 10, 25, 4, 0, tzinfo=UTC).isoformat()
    intent = interpret_instruction("Use the reviewed need and recommend the next action.").model_copy(
        update={
            "context_requirements": [
                "business_need_assessment_context",
                "business_need_knowledge_context",
            ]
        }
    )

    jobs = route_jobs_for_intent(intent)
    assert "business.review_need_with_knowledge" in {job.job_key for job in jobs}
    assert "business.review_need" not in {job.job_key for job in jobs}
    selections, missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    assert missing == []

    steps = compile_planned_steps(
        selections,
        intent=intent,
        business_need_assessment_context=context,
    )
    step = next(item for item in steps if item.job_key == "business.review_need_with_knowledge")
    assert step.action_name == "knowledge.inform_decision"
    assert step.output_contract == "recommendation"
    payload = KnowledgeInformedDecisionSupportInput.model_validate(step.tool_input)
    assert payload.query.goal_semantic_signature.objective_key == "customer_acquisition"
    assert payload.applicability_context.subject_refs[0].object_id == "1devteam"
    assert payload.applicability_context.evaluated_at == datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
    assert payload.decision.evidence[0].evidence_id.startswith("assessment:")


def test_semantically_complete_assessment_falls_back_to_existing_decision_when_knowledge_is_not_charter_allowed() -> (
    None
):
    context = _assessment_context()
    context["subject_references"] = [{"schema_version": 1, "object_type": "organization", "object_id": "1devteam"}]
    intent = interpret_instruction("Use the reviewed need and recommend the next action.").model_copy(
        update={
            "context_requirements": [
                "business_need_assessment_context",
                "business_need_knowledge_context",
            ]
        }
    )
    base = default_operating_charter()
    restricted = base.__class__(
        schema_version=base.schema_version,
        may_prepare=tuple(action for action in base.may_prepare if action != "knowledge.inform_decision"),
        may_perform=base.may_perform,
        never_do=base.never_do,
        approval_mode=base.approval_mode,
        escalation_email=base.escalation_email,
        escalation_phone=base.escalation_phone,
        source=base.source,
        revision=base.revision,
    )

    selections, missing = resolve_jobs(route_jobs_for_intent(intent), intent=intent, charter=restricted)
    assert missing == []
    selected = next(item for item in selections if item.job_key == "business.review_need_with_knowledge")
    assert selected.action_name == "decision.recommend_next_action"
    assert selected.readiness == "ready"
    assert {item.action for item in selected.alternatives} == {"knowledge.inform_decision"}

    step = next(
        item
        for item in compile_planned_steps(
            selections,
            intent=intent,
            business_need_assessment_context=context,
        )
        if item.job_key == "business.review_need_with_knowledge"
    )
    assert (
        DecisionRecommendInput.model_validate(step.tool_input).context["assessment_evidence_class"]
        == "derived_noncanonical"
    )


def test_validated_assessment_reference_snapshots_owner_context_without_execution_authority() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    assessment_id = uuid.UUID("0a3cfa70-1df6-4de6-a042-5e7b344b10d8")
    need = SimpleNamespace(
        id=uuid.uuid4(),
        need_id="need-customer-acquisition",
        revision=3,
        status="recognized",
        condition_summary="Customer acquisition is below the approved target.",
        subject_references=[],
        objective_reference={"objective_key": "customer_acquisition"},
    )
    payload = _assessment_context()
    assessment = SimpleNamespace(
        id=assessment_id,
        need_id=need.need_id,
        need_revision=need.revision,
        assessment_fingerprint="sha256:" + "a" * 64,
        assessment_json={**payload, "tenant_id": tenant_id},
    )
    with patch("backend.services.mission_composition.service.BusinessUnderstandingRepository") as repository_cls:
        repository_cls.return_value.get_need_revision_for_tenant.return_value = need
        repository_cls.return_value.get_assessment_for_tenant.return_value = assessment
        service = MissionCompositionService(db=MagicMock())
        need_reference = service._business_need_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={"need_id": need.need_id, "revision": need.revision},
        )
        reference = service._business_need_assessment_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={"assessment_id": str(assessment_id)},
            need_reference=need_reference,
        )

    assert reference is not None
    assert reference["assessment_context"]["candidate_responses"] == payload["candidate_responses"]
    assert reference["assessment_context_sha256"].startswith("sha256:")
    assert reference["grants_execution_authority"] is False


def test_validated_assessment_reference_preserves_only_a_selected_candidate() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    assessment_id = uuid.UUID("0a3cfa70-1df6-4de6-a042-5e7b344b10d8")
    need = SimpleNamespace(
        id=uuid.uuid4(),
        need_id="need-customer-acquisition",
        revision=3,
        status="recognized",
        condition_summary="Customer acquisition is below the approved target.",
        subject_references=_baseline_measurement().subject_references,
        objective_reference={"objective_key": "customer_acquisition"},
    )
    payload = _assessment_context()
    assessment = SimpleNamespace(
        id=assessment_id,
        need_id=need.need_id,
        need_revision=need.revision,
        assessment_fingerprint="sha256:" + "a" * 64,
        assessment_json={**payload, "tenant_id": tenant_id},
    )
    with patch("backend.services.mission_composition.service.BusinessUnderstandingRepository") as repository_cls:
        repository_cls.return_value.get_need_revision_for_tenant.return_value = need
        repository_cls.return_value.get_assessment_for_tenant.return_value = assessment
        baseline = _baseline_measurement()
        repository_cls.return_value.get_measurement_for_tenant.return_value = baseline
        service = MissionCompositionService(db=MagicMock())
        need_reference = service._business_need_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={"need_id": need.need_id, "revision": need.revision},
        )
        reference = service._business_need_assessment_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={
                "assessment_id": str(assessment_id),
                "selected_candidate_response_key": "improve_lead_qualification",
                "baseline_measurement_id": str(baseline.id),
            },
            need_reference=need_reference,
        )
        with pytest.raises(MissionCompositionError, match="not a candidate"):
            service._business_need_assessment_reference(
                db=service._db,
                tenant_id=tenant_id,
                reference={"assessment_id": str(assessment_id), "selected_candidate_response_key": "run_outreach"},
                need_reference=need_reference,
            )

    assert reference is not None
    assert reference["selected_candidate_response_key"] == "improve_lead_qualification"
    assert reference["baseline_measurement_id"] == str(baseline.id)
    advancement = reference["response_advancement"]
    assert advancement["baseline_measurement"]["measurement_id"] == str(baseline.id)
    assert advancement["intended_measurement"]["comparison_required"] is True
    assert advancement["grants_execution_authority"] is False
    assert "selected_candidate_response_key" not in reference["assessment_context"]
    assert reference["grants_execution_authority"] is False


def test_selected_response_fails_closed_when_baseline_measurement_is_not_tenant_owned() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    assessment_id = uuid.UUID("0a3cfa70-1df6-4de6-a042-5e7b344b10d8")
    need = SimpleNamespace(
        id=uuid.uuid4(),
        need_id="need-customer-acquisition",
        revision=3,
        status="recognized",
        condition_summary="Customer acquisition is below the approved target.",
        subject_references=[],
        objective_reference={"objective_key": "customer_acquisition"},
    )
    assessment = SimpleNamespace(
        id=assessment_id,
        need_id=need.need_id,
        need_revision=need.revision,
        assessment_fingerprint="sha256:" + "a" * 64,
        assessment_json={**_assessment_context(), "tenant_id": tenant_id},
    )
    with patch("backend.services.mission_composition.service.BusinessUnderstandingRepository") as repository_cls:
        repository_cls.return_value.get_need_revision_for_tenant.return_value = need
        repository_cls.return_value.get_assessment_for_tenant.return_value = assessment
        repository_cls.return_value.get_measurement_for_tenant.return_value = None
        service = MissionCompositionService(db=MagicMock())
        need_reference = service._business_need_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={"need_id": need.need_id, "revision": need.revision},
        )

        with pytest.raises(MissionCompositionError, match="baseline measurement was not found for tenant"):
            service._business_need_assessment_reference(
                db=service._db,
                tenant_id=tenant_id,
                reference={
                    "assessment_id": str(assessment_id),
                    "selected_candidate_response_key": "improve_lead_qualification",
                    "baseline_measurement_id": str(_baseline_measurement().id),
                },
                need_reference=need_reference,
            )


def test_response_advancement_requires_the_complete_reference_set() -> None:
    assessment_id = uuid.UUID("0a3cfa70-1df6-4de6-a042-5e7b344b10d8")

    with pytest.raises(ValueError, match="requires a baseline measurement"):
        ComposeMissionRequest(
            instruction="Prepare the successor mission.",
            business_need_assessment_id=assessment_id,
            business_need_response_key="improve_lead_qualification",
        ).assessment_reference()
    with pytest.raises(ValueError, match="requires a selected business need response"):
        ComposeMissionRequest(
            instruction="Prepare the successor mission.",
            business_need_assessment_id=assessment_id,
            business_need_baseline_measurement_id=_baseline_measurement().id,
        ).assessment_reference()


@pytest.mark.parametrize("mismatch", ["subject", "objective"])
def test_selected_response_rejects_baseline_from_another_need(mismatch: str) -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    assessment_id = uuid.UUID("0a3cfa70-1df6-4de6-a042-5e7b344b10d8")
    baseline = _baseline_measurement()
    need_subjects = list(baseline.subject_references)
    objective_key = baseline.objective_key
    if mismatch == "subject":
        need_subjects = [{"schema_version": 1, "object_type": "organization", "object_id": "different"}]
    else:
        objective_key = "different_objective"
    need = SimpleNamespace(
        id=uuid.uuid4(),
        need_id="need-customer-acquisition",
        revision=3,
        status="recognized",
        condition_summary="Customer acquisition is below the approved target.",
        subject_references=need_subjects,
        objective_reference={"objective_key": objective_key},
    )
    assessment = SimpleNamespace(
        id=assessment_id,
        need_id=need.need_id,
        need_revision=need.revision,
        assessment_fingerprint="sha256:" + "a" * 64,
        assessment_json={**_assessment_context(), "tenant_id": tenant_id},
    )
    with patch("backend.services.mission_composition.service.BusinessUnderstandingRepository") as repository_cls:
        repository_cls.return_value.get_need_revision_for_tenant.return_value = need
        repository_cls.return_value.get_assessment_for_tenant.return_value = assessment
        repository_cls.return_value.get_measurement_for_tenant.return_value = baseline
        service = MissionCompositionService(db=MagicMock())
        need_reference = service._business_need_reference(
            db=service._db,
            tenant_id=tenant_id,
            reference={"need_id": need.need_id, "revision": need.revision},
        )
        with pytest.raises(MissionCompositionError, match="does not match the originating business need"):
            service._business_need_assessment_reference(
                db=service._db,
                tenant_id=tenant_id,
                reference={
                    "assessment_id": str(assessment_id),
                    "selected_candidate_response_key": "improve_lead_qualification",
                    "baseline_measurement_id": str(baseline.id),
                },
                need_reference=need_reference,
            )
