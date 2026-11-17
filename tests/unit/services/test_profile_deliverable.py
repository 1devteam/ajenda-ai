from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.mission_composition.profile_deliverable import assemble_profile_deliverable


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
