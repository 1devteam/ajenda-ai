from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.business_profile.company_introduction import build_company_introduction
from backend.services.mission_composition.profile_deliverable import assemble_profile_deliverable
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
from backend.services.worker_runtime_contracts import _validate_declared_output_contract


def _mission() -> Mission:
    mission = Mission(
        id=uuid.uuid4(),
        tenant_id="tenant-profile",
        objective="Read the approved business profile.",
        status="completed",
        compliance_category="operational",
        jurisdiction="US-ALL",
    )
    now = datetime.now(UTC)
    mission.created_at = now
    mission.updated_at = now
    return mission


def _task(mission: Mission, payload: dict[str, object]) -> ExecutionTask:
    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        title="Profile read",
        description="Read approved profile",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "expected_output_contract": {"artifact": "business_profile_facts"},
            "handler_result": {"output": {"business_profile_facts": payload}},
        },
        requires_human_review=False,
    )
    now = datetime.now(UTC)
    task.created_at = now
    task.updated_at = now
    return task


def test_profile_deliverable_is_typed_and_authority_free() -> None:
    mission = _mission()
    deliverable = assemble_profile_deliverable(
        mission=mission,
        tasks=[
            _task(
                mission,
                {
                    "approved_facts": {"business_name": {"value": "Acme"}},
                    "profile_brief": {"facts": {"business_name": "Acme"}, "missing_fields": []},
                    "profile_id": str(uuid.uuid4()),
                },
            )
        ],
    )

    assert deliverable.kind == "business_profile_brief"
    assert deliverable.complete is True
    assert deliverable.grants_execution_authority is False


def test_profile_source_refs_require_matching_collected_producer_evidence() -> None:
    mission = _mission()
    payload = {
        "approved_facts": {},
        "profile_brief": {"facts": {}},
        "profile_id": str(uuid.uuid4()),
        "source": "approved_business_profile",
    }
    task = _task(mission, payload)
    other_task = _task(mission, payload)

    def evidence(task_id: uuid.UUID, content: dict[str, object], status: str = "collected") -> EvidenceRecord:
        return EvidenceRecord(
            id=uuid.uuid4(),
            tenant_id=mission.tenant_id,
            mission_id=mission.id,
            execution_task_id=task_id,
            evidence_type="action_result",
            evidence_source="test",
            summary="test",
            structured_payload={"business_profile_facts": content},
            collection_status=status,
        )

    matching = evidence(task.id, payload)
    unrelated = evidence(other_task.id, payload)
    different = evidence(task.id, {**payload, "profile_id": str(uuid.uuid4())})
    failed = evidence(task.id, payload, "failed")
    result = assemble_profile_deliverable(
        mission=mission, tasks=[task], evidence_records=[matching, unrelated, different, failed]
    )

    assert result.profile_source_evidence_ids == (matching.id,)
    assert len(result.evidence_ids) == 4


def test_profile_deliverable_fails_closed_for_missing_artifact() -> None:
    mission = _mission()
    with pytest.raises(ValueError, match="artifact is absent"):
        assemble_profile_deliverable(mission=mission, tasks=[])


def test_business_review_is_available_in_profile_deliverable() -> None:
    mission = _mission()
    profile = _task(mission, {"approved_facts": {}, "profile_brief": {"facts": {}}})
    review = _task(mission, {})
    report = {
        "income_opportunities": [{"title": "Test demand"}],
        "supporting_evidence": ["profile:1"],
        "estimated_business_impact": ["Not estimated"],
        "confidence": 0.5,
        "assumptions": ["Unverified"],
        "evidence_gaps": ["Revenue"],
    }
    review.metadata_json = {
        "expected_output_contract": {"artifact": "business_review_report"},
        "handler_result": {"output": {"business_review_report": report}},
    }
    result = assemble_profile_deliverable(mission=mission, tasks=[profile, review])
    assert result.artifacts["business_review_report"] == report
    assert result.complete


def test_missing_declared_review_does_not_mark_profile_deliverable_complete() -> None:
    mission = _mission()
    profile = _task(mission, {"approved_facts": {}, "profile_brief": {"facts": {}}})
    review = _task(mission, {})
    review.metadata_json = {"expected_output_contract": {"artifact": "business_review_report"}}
    result = assemble_profile_deliverable(mission=mission, tasks=[profile, review])
    assert not result.complete


def test_invalid_declared_review_does_not_mark_profile_deliverable_complete() -> None:
    mission = _mission()
    profile = _task(mission, {"approved_facts": {}, "profile_brief": {"facts": {}}})
    review = _task(mission, {})
    review.metadata_json = {
        "expected_output_contract": {"artifact": "business_review_report"},
        "handler_result": {"output": {"business_review_report": {"income_opportunities": []}}},
    }
    result = assemble_profile_deliverable(mission=mission, tasks=[profile, review])
    assert not result.complete
    assert "business_review_report" not in result.artifacts


def test_company_introduction_from_composed_task_is_readable_and_tenant_scoped() -> None:
    mission = _mission()
    mission.objective = (
        "Search Ajenda's approved business profile and governed internal memory, then prepare an evidence-backed "
        "company brief and a draft introduction explaining who Ajenda is, what it provides, who it serves, "
        "and what makes it different. Do not browse the web, contact anyone, send email, modify CRM records, "
        "or perform any external action."
    )
    plan = MissionCompositionService(db=None).compose(tenant_id=mission.tenant_id, instruction=mission.objective)
    assert plan.ready_to_start
    assert plan.intent.requested_quantity == 1
    assert plan.allowed_actions == ["retrieval.hybrid_search"]
    step = plan.planned_steps[0]
    invocation = ToolInvocation(action=step.action_name, input=step.tool_input)

    profile = SimpleNamespace(
        id=uuid.uuid4(),
        approved_facts={
            "business_name": "Ajenda AI",
            "description": "Governed AI operations.",
            "products_services": ["Mission planning"],
            "target_customers": ["Operator-led teams"],
            "differentiators": ["Disputed claim"],
        },
        provenance={"differentiators": {"conflict": True}},
    )
    session_factory = MagicMock()
    memory = MagicMock()
    memory.keyword_search.return_value = [
        {"id": "memory-1", "tenant_id": mission.tenant_id, "content": "Unsupported memory claim"},
        {"id": "foreign-memory", "tenant_id": "other-tenant"},
    ]
    with (
        patch("backend.services.tools.retrieval_actions.BusinessProfileRepository") as repository,
        patch("backend.services.tools.retrieval_actions.activate_tenant_session") as tenant_session,
        patch("backend.services.tools.retrieval_actions.resolve_memory_chunk_store", return_value=memory),
        patch("backend.services.tools.retrieval_actions.resolve_record_store") as record_store,
        patch("backend.services.tools.retrieval_actions.resolve_business_context") as business_context,
    ):
        repository.return_value.get_active_profile_for_tenant.return_value = profile
        result = get_default_action_registry().invoke(
            invocation,
            ActionRuntimeContext(
                tenant_id=mission.tenant_id,
                task_id=uuid.uuid4(),
                mission_id=mission.id,
                worker_id="worker",
                lease_id="lease",
                session_factory=session_factory,
            ),
        )
    tenant_session.assert_called_once_with(session_factory.return_value, mission.tenant_id)
    repository.return_value.get_active_profile_for_tenant.assert_called_once_with(tenant_id=mission.tenant_id)
    memory.keyword_search.assert_called_once_with(tenant_id=mission.tenant_id, query="Ajenda AI", limit=5)
    memory.vector_search.assert_not_called()
    record_store.assert_not_called()
    business_context.assert_not_called()
    assert result.side_effect_class == SideEffectClass.INTERNAL_READ

    payload = result.output["business_profile_facts"]
    task = _task(mission, payload)
    task.metadata_json["tool_invocation"] = invocation.model_dump(mode="json")
    _validate_declared_output_contract(task, {"output": result.output})
    evidence_id = uuid.uuid4()
    evidence = EvidenceRecord(
        id=evidence_id,
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        execution_task_id=task.id,
        evidence_type="action_result",
        evidence_source="retrieval_actions",
        structured_payload=result.evidence[0].structured_payload,
        collection_status="collected",
    )
    read = assemble_profile_deliverable(mission=mission, tasks=[task], evidence_records=[evidence])
    assert read.complete
    assert read.profile_source_evidence_ids == (evidence_id,)
    assert read.conflicting_fields == ("differentiators",)
    draft = read.company_introduction_draft
    assert draft is not None and draft.status == "draft"
    assert draft.memory_reference_ids == ("memory-1",)
    assert draft.memory_lookup_status == "matched"
    assert draft.source_fields == ("business_name", "description", "products_services", "target_customers")
    assert "Mission planning" in draft.body
    assert "Disputed claim" not in draft.body
    assert "Unsupported memory claim" not in draft.body

    without_draft = {key: value for key, value in payload.items() if key != "company_introduction_draft"}
    with pytest.raises(ValueError, match="CompanyIntroductionDraft"):
        _validate_declared_output_contract(task, {"output": {"business_profile_facts": without_draft}})


@pytest.mark.parametrize(
    "facts,conflicts",
    [
        ({"business_name": "Ajenda AI"}, []),
        ({"business_name": "Ajenda AI", "description": "Governed AI operations."}, ["company"]),
    ],
)
def test_company_introduction_requires_usable_approved_facts(facts: dict[str, str], conflicts: list[str]) -> None:
    with pytest.raises(ValueError, match="unconflicted business name and at least one descriptive fact"):
        build_company_introduction({"facts": facts, "conflicting_fields": conflicts}, memory_reference_ids=())
